from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from types import TracebackType
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    prompt: str
    model: str
    instructions: str
    max_output_tokens: int
    safety_identifier: str


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None


@dataclass(frozen=True, slots=True)
class GenerationResult:
    text: str
    provider_response_id: str
    usage: TokenUsage


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class RefusalDelta:
    text: str


@dataclass(frozen=True, slots=True)
class ProviderCompleted:
    provider_response_id: str
    usage: TokenUsage


ProviderEvent = TextDelta | RefusalDelta | ProviderCompleted


class ProviderError(Exception):
    def __init__(
        self,
        *,
        code: str,
        safe_message: str,
        retriable: bool,
        provider_response_id: str | None = None,
        usage: TokenUsage | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.retriable = retriable
        self.provider_response_id = provider_response_id
        self.usage = usage


class LLMProvider(Protocol):
    def stream(
        self,
        request: ProviderRequest,
    ) -> AsyncGenerator[ProviderEvent, None]: ...

    async def generate(self, request: ProviderRequest) -> GenerationResult: ...

    async def close(self) -> None: ...


class ProviderContext:
    """Optional helper for providers used outside FastAPI lifespan management."""

    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    async def __aenter__(self) -> LLMProvider:
        return self.provider

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.provider.close()
