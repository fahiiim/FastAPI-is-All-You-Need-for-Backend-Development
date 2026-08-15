from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import DemoPrincipal
from app.config import Settings
from app.models import GenerationJob, JobStatus
from app.schemas import GenerationInput


class IdempotencyConflictError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class CreatedJob:
    job: GenerationJob
    created: bool


def _mac(secret: str, value: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), value, hashlib.sha256).hexdigest()


def _request_fingerprint(
    payload: GenerationInput,
    settings: Settings,
) -> str:
    canonical = json.dumps(
        {
            "instructions": settings.instructions,
            "max_output_tokens": payload.max_output_tokens,
            "model": settings.model,
            "prompt": payload.prompt,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _mac(settings.idempotency_secret.get_secret_value(), canonical)


def _idempotency_hash(value: str | None, settings: Settings) -> str | None:
    if value is None:
        return None
    return _mac(
        settings.idempotency_secret.get_secret_value(),
        value.encode("utf-8"),
    )


async def create_job(
    session: AsyncSession,
    *,
    principal: DemoPrincipal,
    payload: GenerationInput,
    idempotency_key: str | None,
    settings: Settings,
) -> CreatedJob:
    key_hash = _idempotency_hash(idempotency_key, settings)
    fingerprint = _request_fingerprint(payload, settings)
    job = GenerationJob(
        client_id=principal.client_id,
        idempotency_key_hash=key_hash,
        request_fingerprint=fingerprint,
        prompt=payload.prompt,
        model_name=settings.model,
        instructions=settings.instructions,
        max_output_tokens=payload.max_output_tokens,
        max_attempts=settings.job_max_attempts,
        status=JobStatus.QUEUED.value,
    )
    session.add(job)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        if key_hash is None:
            raise
        existing = await session.scalar(
            select(GenerationJob).where(
                GenerationJob.client_id == principal.client_id,
                GenerationJob.idempotency_key_hash == key_hash,
            )
        )
        if existing is None:
            raise
        if existing.request_fingerprint != fingerprint:
            raise IdempotencyConflictError from None
        return CreatedJob(job=existing, created=False)

    await session.refresh(job)
    return CreatedJob(job=job, created=True)


async def get_job(
    session: AsyncSession,
    *,
    principal: DemoPrincipal,
    job_id: object,
) -> GenerationJob | None:
    return await session.scalar(
        select(GenerationJob).where(
            GenerationJob.id == job_id,
            GenerationJob.client_id == principal.client_id,
        )
    )
