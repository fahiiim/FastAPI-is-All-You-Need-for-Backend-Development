import json
import time
from datetime import UTC, datetime
from uuid import UUID

from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from .celery_app import celery
from .config import get_settings
from .database import ExportJob, OutboxMessage, SessionFactory

redis = Redis.from_url(get_settings().redis_url, decode_responses=True)


@celery.task(name="exports.dispatch_outbox")
def dispatch_outbox() -> int:
    published = 0
    with SessionFactory.begin() as session:
        messages = list(
            session.scalars(
                select(OutboxMessage)
                .where(OutboxMessage.published_at.is_(None))
                .order_by(OutboxMessage.created_at)
                .with_for_update(skip_locked=True)
                .limit(100)
            )
        )
        for message in messages:
            payload = json.loads(message.payload)
            run_export.apply_async(
                args=[payload["job_id"]],
                task_id=f"export-{payload['job_id']}",
            )
            message.published_at = datetime.now(UTC)
            published += 1
    return published


def claim_job(session: Session, job_id: UUID) -> ExportJob | None:
    job = session.scalar(
        select(ExportJob).where(ExportJob.id == job_id).with_for_update()
    )
    if job is None or job.status == "completed":
        return None
    if job.status == "running":
        return None
    job.status = "running"
    job.error_code = None
    return job


@celery.task(
    bind=True,
    name="exports.run_export",
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=4,
)
def run_export(self, job_id_text: str) -> str:
    job_id = UUID(job_id_text)
    with SessionFactory.begin() as session:
        job = claim_job(session, job_id)
        if job is None:
            return "already-claimed-or-complete"

    progress_key = f"export-progress:v1:{job_id}"
    for percent in (10, 40, 70, 100):
        time.sleep(0.25)
        redis.set(progress_key, percent, ex=3600)

    with SessionFactory.begin() as session:
        job = session.get(ExportJob, job_id, with_for_update=True)
        if job is None:
            return "deleted"
        job.status = "completed"
        job.result_uri = f"s3://example-exports/{job.id}.json"
    return "completed"
