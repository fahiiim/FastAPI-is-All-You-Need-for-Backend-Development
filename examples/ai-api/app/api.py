from __future__ import annotations

import asyncio
import hashlib
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.auth import DemoPrincipal, get_settings, require_demo_principal
from app.config import Settings
from app.database import Database, get_session
from app.jobs import IdempotencyConflictError, create_job, get_job
from app.providers.base import LLMProvider, ProviderRequest
from app.schemas import GenerationInput, JobAccepted, JobView
from app.sse import StreamLease, generate_sse

router = APIRouter()


def _validate_request_limits(payload: GenerationInput, settings: Settings) -> None:
    if len(payload.prompt) > settings.max_prompt_chars:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="prompt exceeds the configured character limit",
        )
    if payload.max_output_tokens > settings.max_output_tokens:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="max_output_tokens exceeds the configured limit",
        )


def _provider_request(
    payload: GenerationInput,
    principal: DemoPrincipal,
    settings: Settings,
) -> ProviderRequest:
    safety_identifier = hashlib.sha256(
        principal.client_id.encode("utf-8")
    ).hexdigest()
    return ProviderRequest(
        prompt=payload.prompt,
        model=settings.model,
        instructions=settings.instructions,
        max_output_tokens=payload.max_output_tokens,
        safety_identifier=safety_identifier,
    )


@router.get("/health/live", tags=["health"])
async def liveness() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/health/ready", tags=["health"])
async def readiness(request: Request) -> dict[str, str]:
    database: Database = request.app.state.database
    try:
        async with database.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc
    return {"status": "ready"}


@router.post("/v1/generations:stream", tags=["generation"])
async def stream_generation(
    payload: GenerationInput,
    request: Request,
    principal: Annotated[DemoPrincipal, Depends(require_demo_principal)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    _validate_request_limits(payload, settings)
    semaphore: asyncio.Semaphore = request.app.state.stream_semaphore
    try:
        await asyncio.wait_for(
            semaphore.acquire(),
            timeout=settings.stream_admission_timeout_seconds,
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="stream capacity is exhausted",
            headers={"Retry-After": "1"},
        ) from exc

    lease = StreamLease(semaphore)
    provider: LLMProvider = request.app.state.provider
    event_stream = generate_sse(
        request=request,
        provider=provider,
        provider_request=_provider_request(payload, principal, settings),
        lease=lease,
        max_output_chars=settings.max_stream_output_chars,
    )
    return StreamingResponse(
        event_stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
        background=BackgroundTask(lease.release),
    )


@router.post(
    "/v1/jobs",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["jobs"],
)
async def submit_job(
    payload: GenerationInput,
    response: Response,
    principal: Annotated[DemoPrincipal, Depends(require_demo_principal)],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", max_length=128),
    ] = None,
) -> JobAccepted:
    _validate_request_limits(payload, settings)
    if idempotency_key is not None and not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key must not be blank",
        )

    try:
        result = await create_job(
            session,
            principal=principal,
            payload=payload,
            idempotency_key=idempotency_key,
            settings=settings,
        )
    except IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency-Key was already used for a different request",
        ) from exc

    response.headers["Location"] = f"/v1/jobs/{result.job.id}"
    return JobAccepted(
        id=result.job.id,
        status=result.job.status,
        created=result.created,
    )


@router.get(
    "/v1/jobs/{job_id}",
    response_model=JobView,
    tags=["jobs"],
)
async def read_job(
    job_id: UUID,
    principal: Annotated[DemoPrincipal, Depends(require_demo_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JobView:
    job = await get_job(
        session,
        principal=principal,
        job_id=job_id,
    )
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="job not found",
        )
    return JobView.from_job(job)

