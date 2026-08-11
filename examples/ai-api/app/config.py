from __future__ import annotations

from enum import StrEnum

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

HARD_MAX_PROMPT_CHARS = 20_000
HARD_MAX_OUTPUT_TOKENS = 4_096
HARD_MAX_OUTPUT_CHARS = 200_000


class ProviderKind(StrEnum):
    FAKE = "fake"
    OPENAI = "openai"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AI_API_",
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str
    demo_api_key: SecretStr
    idempotency_secret: SecretStr

    provider: ProviderKind = ProviderKind.FAKE
    model: str = Field(default="fake-text-v1", min_length=1, max_length=200)
    openai_api_key: SecretStr | None = None
    instructions: str = Field(
        default=(
            "Answer the user's request directly. State uncertainty when the supplied "
            "context is insufficient."
        ),
        min_length=1,
        max_length=2_000,
    )

    auto_create_schema: bool = False
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=5, ge=0, le=50)
    database_pool_timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    max_prompt_chars: int = Field(default=8_000, ge=1, le=HARD_MAX_PROMPT_CHARS)
    max_output_tokens: int = Field(default=1_024, ge=1, le=HARD_MAX_OUTPUT_TOKENS)
    max_stream_output_chars: int = Field(
        default=40_000, ge=1, le=HARD_MAX_OUTPUT_CHARS
    )
    max_stored_output_chars: int = Field(
        default=40_000, ge=1, le=HARD_MAX_OUTPUT_CHARS
    )

    stream_concurrency: int = Field(default=8, ge=1, le=100)
    stream_admission_timeout_seconds: float = Field(default=0.25, gt=0, le=30)
    provider_timeout_seconds: float = Field(default=60.0, gt=0, le=600)

    worker_concurrency: int = Field(default=2, ge=1, le=32)
    worker_poll_seconds: float = Field(default=0.5, gt=0, le=30)
    job_lease_seconds: int = Field(default=90, ge=10, le=3_600)
    job_max_attempts: int = Field(default=3, ge=1, le=10)
    job_retry_base_seconds: float = Field(default=1.0, ge=0, le=300)

    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR)$")

    @model_validator(mode="after")
    def validate_security_and_time_budget(self) -> Settings:
        if len(self.demo_api_key.get_secret_value()) < 24:
            raise ValueError("demo_api_key must contain at least 24 characters")
        if len(self.idempotency_secret.get_secret_value()) < 32:
            raise ValueError("idempotency_secret must contain at least 32 characters")
        if self.provider is ProviderKind.OPENAI:
            if self.openai_api_key is None or not self.openai_api_key.get_secret_value():
                raise ValueError("openai_api_key is required when provider=openai")
        if self.job_lease_seconds <= self.provider_timeout_seconds + 5:
            raise ValueError(
                "job_lease_seconds must exceed provider_timeout_seconds by more than 5"
            )
        return self

