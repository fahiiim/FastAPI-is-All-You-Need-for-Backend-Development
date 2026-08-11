import json
import secrets
from hashlib import sha256
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from pydantic import BaseModel, Field
from redis import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .database import ExportJob, IdempotencyRecord, OutboxMessage, get_session

app = FastAPI(title="Distributed Export API", version="1.0.0")
redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
SessionDep = Annotated[Session, Depends(get_session)]


class ExportCreate(BaseModel):
    report_type: str = Field(min_length=1, max_length=100)


class ExportRead(BaseModel):
    id: UUID
    report_type: str
    status: Literal["queued", "running", "completed", "failed"]
    progress_percent: int | None = None
    result_uri: str | None = None
    error_code: str | None = None


def require_account(
    x_api_key: Annotated[str | None, Header()] = None,
) -> str:
    if x_api_key is None or not secrets.compare_digest(x_api_key, get_settings().api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return "demo-account"


def as_response(job: ExportJob) -> ExportRead:
    try:
        raw_progress = redis.get(f"export-progress:v1:{job.id}")
    except ConnectionError:
        raw_progress = None
    return ExportRead(
        id=job.id,
        report_type=job.report_type,
        status=job.status,
        progress_percent=int(raw_progress) if raw_progress is not None else None,
        result_uri=job.result_uri,
        error_code=job.error_code,
    )


@app.post("/v1/exports", response_model=ExportRead, status_code=status.HTTP_202_ACCEPTED)
def create_export(
    payload: ExportCreate,
    response: Response,
    session: SessionDep,
    account_id: Annotated[str, Depends(require_account)],
    idempotency_key: Annotated[str, Header(min_length=8, max_length=200)],
) -> ExportRead:
    canonical = payload.model_dump_json()
    request_hash = sha256(canonical.encode()).hexdigest()
    existing = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.account_id == account_id,
            IdempotencyRecord.key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Idempotency key payload mismatch")
        job = session.get(ExportJob, existing.job_id)
        if job is None:
            raise HTTPException(status_code=500, detail="Idempotency record is inconsistent")
        response.headers["Location"] = f"/v1/exports/{job.id}"
        return as_response(job)

    job = ExportJob(account_id=account_id, report_type=payload.report_type)
    session.add(job)
    session.flush()
    session.add(
        IdempotencyRecord(
            account_id=account_id,
            key=idempotency_key,
            request_hash=request_hash,
            job_id=job.id,
        )
    )
    session.add(
        OutboxMessage(
            topic="exports.requested",
            aggregate_id=job.id,
            payload=json.dumps({"job_id": str(job.id)}),
        )
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Idempotency key conflict") from exc
    response.headers["Location"] = f"/v1/exports/{job.id}"
    return as_response(job)


@app.get("/v1/exports/{job_id}", response_model=ExportRead)
def read_export(
    job_id: UUID,
    session: SessionDep,
    account_id: Annotated[str, Depends(require_account)],
) -> ExportRead:
    job = session.scalar(
        select(ExportJob).where(ExportJob.id == job_id, ExportJob.account_id == account_id)
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Export not found")
    return as_response(job)


@app.get("/health/live", include_in_schema=False)
def live() -> dict[str, str]:
    return {"status": "ok"}
