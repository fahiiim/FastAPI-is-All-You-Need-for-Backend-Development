from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import AsyncGenerator
from uuid import uuid4

from app.providers.base import (
    GenerationResult,
    ProviderCompleted,
    ProviderError,
    ProviderEvent,
    ProviderRequest,
    TextDelta,
    TokenUsage,
)


@dataclass(frozen=True, slots=True)
class FakeBehavior:
    chunk_size: int = 12
    chunk_delay_seconds: float = 0.0
    fail_prompts: frozenset[str] = field(default_factory=frozenset)
    fail_after_chunks: int | None = None
    failure_retriable: bool = False


class FakeProvider:
    """Deterministic provider for local development and tests."""

    def __init__(self, behavior: FakeBehavior | None = None) -> None:
        self.behavior = behavior or FakeBehavior()
        self.closed = False

    @staticmethod
    def _render(request: ProviderRequest) -> str:
        words = f"Fake provider response: {request.prompt}".split()
        return " ".join(words[: request.max_output_tokens])

    @staticmethod
    def _usage(request: ProviderRequest, text: str) -> TokenUsage:
        input_tokens = len(request.prompt.split())
        output_tokens = len(text.split())
        return TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )

    def _should_fail(self, request: ProviderRequest) -> bool:
        return request.prompt in self.behavior.fail_prompts

    def _failure(self) -> ProviderError:
        return ProviderError(
            code="fake_provider_failure",
            safe_message="the configured fake provider failed",
            retriable=self.behavior.failure_retriable,
        )

    async def generate(self, request: ProviderRequest) -> GenerationResult:
        if self._should_fail(request):
            raise self._failure()
        if self.behavior.chunk_delay_seconds:
            await asyncio.sleep(self.behavior.chunk_delay_seconds)

        text = self._render(request)
        return GenerationResult(
            text=text,
            provider_response_id=f"fake_{uuid4().hex}",
            usage=self._usage(request, text),
        )

    async def stream(
        self,
        request: ProviderRequest,
    ) -> AsyncGenerator[ProviderEvent, None]:
        text = self._render(request)
        response_id = f"fake_{uuid4().hex}"
        emitted_chunks = 0

        if self._should_fail(request) and self.behavior.fail_after_chunks is None:
            raise self._failure()

        for offset in range(0, len(text), self.behavior.chunk_size):
            if self.behavior.chunk_delay_seconds:
                await asyncio.sleep(self.behavior.chunk_delay_seconds)
            if (
                self._should_fail(request)
                and self.behavior.fail_after_chunks == emitted_chunks
            ):
                raise self._failure()
            emitted_chunks += 1
            yield TextDelta(text[offset : offset + self.behavior.chunk_size])

        if (
            self._should_fail(request)
            and self.behavior.fail_after_chunks == emitted_chunks
        ):
            raise self._failure()

        yield ProviderCompleted(
            provider_response_id=response_id,
            usage=self._usage(request, text),
        )

    async def close(self) -> None:
        self.closed = True

