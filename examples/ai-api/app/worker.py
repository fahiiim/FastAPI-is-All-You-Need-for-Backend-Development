from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select, update

from app.config import Settings
from app.database import Database
from app.models import GenerationJob, JobStatus
from app.providers import build_provider
from app.providers.base import (
    GenerationResult,
    LLMProvider,
    ProviderError,
    ProviderRequest,
    TokenUsage,
)

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    id: UUID
    client_id: str
    prompt: str
    model: str
    instructions: str
    max_output_tokens: int
    attempt: int
    max_attempts: int

    def provider_request(self) -> ProviderRequest:
        safety_identifier = hashlib.sha256(
            self.client_id.encode("utf-8")
        ).hexdigest()
        return ProviderRequest(
            prompt=self.prompt,
            model=self.model,
            instructions=self.instructions,
            max_output_tokens=self.max_output_tokens,
            safety_identifier=safety_identifier,
        )


class JobWorker:
    def __init__(
        self,
        *,
        database: Database,
        provider: LLMProvider,
        settings: Settings,
    ) -> None:
        self.database = database
        self.provider = provider
        self.settings = settings

    async def _claim_one(self, worker_id: str) -> ClaimedJob | None:
        now = utc_now()
        lease_expires_at = now + timedelta(seconds=self.settings.job_lease_seconds)

        async with self.database.session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(GenerationJob)
                    .where(
                        GenerationJob.status == JobStatus.RUNNING.value,
                        GenerationJob.lease_expires_at <= now,
                        GenerationJob.attempts >= GenerationJob.max_attempts,
                    )
                    .values(
                        status=JobStatus.FAILED.value,
                        error_code="worker_lease_exhausted",
                        error_message="the worker stopped before completing the job",
                        worker_id=None,
                        lease_expires_at=None,
                        completed_at=now,
                        updated_at=now,
                    )
                )

                eligible = or_(
                    GenerationJob.status == JobStatus.QUEUED.value,
                    and_(
                        GenerationJob.status == JobStatus.RUNNING.value,
                        GenerationJob.lease_expires_at <= now,
                    ),
                )
                statement = (
                    select(GenerationJob)
                    .where(
                        eligible,
                        GenerationJob.available_at <= now,
                        GenerationJob.attempts < GenerationJob.max_attempts,
                    )
                    .order_by(GenerationJob.available_at, GenerationJob.created_at)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                job = await session.scalar(statement)
                if job is None:
                    return None

                job.status = JobStatus.RUNNING.value
                job.worker_id = worker_id
                job.lease_expires_at = lease_expires_at
                job.attempts += 1
                job.started_at = job.started_at or now
                job.updated_at = now
                job.error_code = None
                job.error_message = None

                return ClaimedJob(
                    id=job.id,
                    client_id=job.client_id,
                    prompt=job.prompt,
                    model=job.model_name,
                    instructions=job.instructions,
                    max_output_tokens=job.max_output_tokens,
                    attempt=job.attempts,
                    max_attempts=job.max_attempts,
                )

    async def _complete(
        self,
        claimed: ClaimedJob,
        worker_id: str,
        result: GenerationResult,
    ) -> None:
        now = utc_now()
        async with self.database.session_factory() as session:
            async with session.begin():
                update_result = await session.execute(
                    update(GenerationJob)
                    .where(
                        GenerationJob.id == claimed.id,
                        GenerationJob.status == JobStatus.RUNNING.value,
                        GenerationJob.worker_id == worker_id,
                    )
                    .values(
                        status=JobStatus.COMPLETED.value,
                        output_text=result.text,
                        provider_response_id=result.provider_response_id,
                        input_tokens=result.usage.input_tokens,
                        output_tokens=result.usage.output_tokens,
                        total_tokens=result.usage.total_tokens,
                        error_code=None,
                        error_message=None,
                        worker_id=None,
                        lease_expires_at=None,
                        completed_at=now,
                        updated_at=now,
                    )
                )
                if update_result.rowcount != 1:
                    logger.warning(
                        "Discarded stale job completion",
                        extra={"job_id": str(claimed.id), "worker_id": worker_id},
                    )

    async def _fail(
        self,
        claimed: ClaimedJob,
        worker_id: str,
        error: ProviderError,
    ) -> None:
        now = utc_now()
        should_retry = error.retriable and claimed.attempt < claimed.max_attempts
        retry_delay = self.settings.job_retry_base_seconds * (
            2 ** (claimed.attempt - 1)
        )
        usage: TokenUsage | None = error.usage

        values: dict[str, object] = {
            "status": (
                JobStatus.QUEUED.value if should_retry else JobStatus.FAILED.value
            ),
            "error_code": error.code,
            "error_message": error.safe_message,
            "provider_response_id": error.provider_response_id,
            "input_tokens": usage.input_tokens if usage is not None else None,
            "output_tokens": usage.output_tokens if usage is not None else None,
            "total_tokens": usage.total_tokens if usage is not None else None,
            "worker_id": None,
            "lease_expires_at": None,
            "available_at": now + timedelta(seconds=retry_delay),
            "completed_at": None if should_retry else now,
            "updated_at": now,
        }

        async with self.database.session_factory() as session:
            async with session.begin():
                update_result = await session.execute(
                    update(GenerationJob)
                    .where(
                        GenerationJob.id == claimed.id,
                        GenerationJob.status == JobStatus.RUNNING.value,
                        GenerationJob.worker_id == worker_id,
                    )
                    .values(**values)
                )
                if update_result.rowcount != 1:
                    logger.warning(
                        "Discarded stale job failure",
                        extra={"job_id": str(claimed.id), "worker_id": worker_id},
                    )

    async def process_one(self, worker_id: str) -> bool:
        claimed = await self._claim_one(worker_id)
        if claimed is None:
            return False

        try:
            result = await asyncio.wait_for(
                self.provider.generate(claimed.provider_request()),
                timeout=self.settings.provider_timeout_seconds,
            )
            if len(result.text) > self.settings.max_stored_output_chars:
                raise ProviderError(
                    code="stored_output_limit",
                    safe_message="the generated output exceeded the storage limit",
                    retriable=False,
                    provider_response_id=result.provider_response_id,
                    usage=result.usage,
                )
        except asyncio.CancelledError:
            logger.info(
                "Worker cancelled with leased job",
                extra={"job_id": str(claimed.id), "worker_id": worker_id},
            )
            raise
        except TimeoutError:
            await self._fail(
                claimed,
                worker_id,
                ProviderError(
                    code="provider_timeout",
                    safe_message="the model provider timed out",
                    retriable=True,
                ),
            )
        except ProviderError as exc:
            await self._fail(claimed, worker_id, exc)
        except Exception:
            logger.exception(
                "Unexpected worker failure",
                extra={"job_id": str(claimed.id), "worker_id": worker_id},
            )
            await self._fail(
                claimed,
                worker_id,
                ProviderError(
                    code="worker_error",
                    safe_message="the worker failed while processing the job",
                    retriable=True,
                ),
            )
        else:
            await self._complete(claimed, worker_id, result)

        return True

    async def _run_slot(self, slot: int) -> None:
        worker_id = f"{socket.gethostname()}:{os.getpid()}:{slot}"
        while True:
            try:
                processed = await self.process_one(worker_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Worker slot failed before claiming or finalizing a job"
                )
                processed = False

            if not processed:
                await asyncio.sleep(self.settings.worker_poll_seconds)

    async def run_forever(self) -> None:
        slots = [
            asyncio.create_task(self._run_slot(slot), name=f"job-worker-{slot}")
            for slot in range(self.settings.worker_concurrency)
        ]
        await asyncio.gather(*slots)


async def run_worker() -> None:
    settings = Settings()  # type: ignore[call-arg]
    logging.basicConfig(level=settings.log_level)
    database = Database(settings)
    provider = build_provider(settings)
    try:
        if settings.auto_create_schema:
            await database.create_schema()
        worker = JobWorker(database=database, provider=provider, settings=settings)
        await worker.run_forever()
    finally:
        await provider.close()
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(run_worker())
