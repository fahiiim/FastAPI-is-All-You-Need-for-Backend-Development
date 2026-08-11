from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import HARD_MAX_OUTPUT_TOKENS, HARD_MAX_PROMPT_CHARS
from app.models import GenerationJob, JobStatus


class GenerationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=HARD_MAX_PROMPT_CHARS)
    max_output_tokens: int = Field(
        default=512,
        ge=1,
        le=HARD_MAX_OUTPUT_TOKENS,
    )

    @field_validator("prompt")
    @classmethod
    def prompt_must_contain_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt must contain non-whitespace text")
        return value


class UsageView(BaseModel):
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None


class JobAccepted(BaseModel):
    id: UUID
    status: JobStatus
    created: bool


class JobView(BaseModel):
    id: UUID
    status: JobStatus
    model: str
    max_output_tokens: int
    attempts: int
    max_attempts: int
    output_text: str | None
    provider_response_id: str | None
    usage: UsageView | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    @classmethod
    def from_job(cls, job: GenerationJob) -> Self:
        has_usage = any(
            value is not None
            for value in (job.input_tokens, job.output_tokens, job.total_tokens)
        )
        usage = (
            UsageView(
                input_tokens=job.input_tokens,
                output_tokens=job.output_tokens,
                total_tokens=job.total_tokens,
            )
            if has_usage
            else None
        )
        return cls(
            id=job.id,
            status=JobStatus(job.status),
            model=job.model_name,
            max_output_tokens=job.max_output_tokens,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
            output_text=job.output_text,
            provider_response_id=job.provider_response_id,
            usage=usage,
            error_code=job.error_code,
            error_message=job.error_message,
            created_at=job.created_at,
            updated_at=job.updated_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
        )

