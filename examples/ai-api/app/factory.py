from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import router
from app.config import Settings
from app.database import Database
from app.providers import build_provider
from app.providers.base import LLMProvider


def create_app(
    settings: Settings | None = None,
    *,
    provider: LLMProvider | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()  # type: ignore[call-arg]
    logging.basicConfig(level=resolved_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(resolved_settings)
        resolved_provider = provider or build_provider(resolved_settings)
        app.state.settings = resolved_settings
        app.state.database = database
        app.state.provider = resolved_provider
        app.state.stream_semaphore = asyncio.Semaphore(
            resolved_settings.stream_concurrency
        )
        try:
            if resolved_settings.auto_create_schema:
                await database.create_schema()
            yield
        finally:
            await resolved_provider.close()
            await database.dispose()

    app = FastAPI(
        title="Durable AI API Reference",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(router)
    return app
