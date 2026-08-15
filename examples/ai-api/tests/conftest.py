from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx2
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.factory import create_app
from app.providers.base import LLMProvider
from app.providers.fake import FakeProvider

TEST_API_KEY = "test-api-key-0123456789abcdef"
TEST_IDEMPOTENCY_SECRET = "test-idempotency-secret-0123456789abcdef"


def build_test_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "sqlite+aiosqlite:///:memory:",
        "demo_api_key": TEST_API_KEY,
        "idempotency_secret": TEST_IDEMPOTENCY_SECRET,
        "provider": "fake",
        "model": "fake-text-v1",
        "auto_create_schema": True,
        "provider_timeout_seconds": 1.0,
        "job_lease_seconds": 10,
        "job_retry_base_seconds": 0,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@dataclass(slots=True)
class AppHarness:
    app: FastAPI
    client: httpx2.AsyncClient
    provider: LLMProvider


@asynccontextmanager
async def running_app(
    settings: Settings,
    provider: LLMProvider | None = None,
) -> AsyncIterator[AppHarness]:
    resolved_provider = provider or FakeProvider()
    application = create_app(settings, provider=resolved_provider)
    async with application.router.lifespan_context(application):
        transport = httpx2.ASGITransport(app=application)
        async with httpx2.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            yield AppHarness(application, client, resolved_provider)


@pytest.fixture
def settings_factory() -> Callable[..., Settings]:
    return build_test_settings


@pytest.fixture
def app_runner() -> Callable[..., object]:
    return running_app


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"X-API-Key": TEST_API_KEY}
