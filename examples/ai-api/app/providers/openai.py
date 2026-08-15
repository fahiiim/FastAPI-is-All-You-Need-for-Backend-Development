from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    OpenAIError,
    RateLimitError,
)

from app.providers.base import (
    GenerationResult,
    ProviderCompleted,
    ProviderError,
    ProviderEvent,
    ProviderRequest,
    RefusalDelta,
    TextDelta,
    TokenUsage,
)

NON_RETRYABLE_LIMIT_CODES = {
    "billing_hard_limit_reached",
    "insufficient_quota",
}
RETRYABLE_RESPONSE_CODES = {
    "rate_limit_exceeded",
    "server_error",
}


def _usage(value: object | None) -> TokenUsage:
    if value is None:
        return TokenUsage(None, None, None)
    return TokenUsage(
        input_tokens=getattr(value, "input_tokens", None),
        output_tokens=getattr(value, "output_tokens", None),
        total_tokens=getattr(value, "total_tokens", None),
    )


def _error_code(value: object) -> str | None:
    direct = getattr(value, "code", None)
    if isinstance(direct, str):
        return direct
    body = getattr(value, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and isinstance(error.get("code"), str):
            return error["code"]
    return None


def _response_error(response: Any) -> ProviderError:
    status = str(getattr(response, "status", "failed"))
    error = getattr(response, "error", None)
    code = _error_code(error) if error is not None else None
    retriable = code in RETRYABLE_RESPONSE_CODES
    return ProviderError(
        code="provider_incomplete" if status == "incomplete" else "provider_failed",
        safe_message="the model provider did not complete the response",
        retriable=retriable,
        provider_response_id=getattr(response, "id", None),
        usage=_usage(getattr(response, "usage", None)),
    )


def _sdk_error(exc: OpenAIError) -> ProviderError:
    if isinstance(exc, APITimeoutError):
        return ProviderError(
            code="provider_timeout",
            safe_message="the model provider timed out",
            retriable=True,
        )
    if isinstance(exc, APIConnectionError):
        return ProviderError(
            code="provider_unavailable",
            safe_message="the model provider is unavailable",
            retriable=True,
        )
    if isinstance(exc, RateLimitError):
        provider_code = _error_code(exc)
        permanent = provider_code in NON_RETRYABLE_LIMIT_CODES
        return ProviderError(
            code="provider_quota_exceeded" if permanent else "provider_rate_limited",
            safe_message=(
                "the model provider quota is unavailable"
                if permanent
                else "the model provider rate limit was reached"
            ),
            retriable=not permanent,
        )
    if isinstance(exc, APIStatusError):
        retriable = exc.status_code in {408, 409, 429} or exc.status_code >= 500
        return ProviderError(
            code="provider_http_error",
            safe_message="the model provider rejected the request",
            retriable=retriable,
        )
    return ProviderError(
        code="provider_error",
        safe_message="the model provider request failed",
        retriable=False,
    )


class OpenAIResponsesProvider:
    def __init__(self, *, api_key: str, timeout_seconds: float) -> None:
        self.client = AsyncOpenAI(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=0,
        )

    @staticmethod
    def _request_kwargs(request: ProviderRequest) -> dict[str, object]:
        return {
            "model": request.model,
            "instructions": request.instructions,
            "input": request.prompt,
            "max_output_tokens": request.max_output_tokens,
            "safety_identifier": request.safety_identifier,
            "store": False,
        }

    async def generate(self, request: ProviderRequest) -> GenerationResult:
        try:
            response = await self.client.responses.create(
                **self._request_kwargs(request)
            )
        except OpenAIError as exc:
            raise _sdk_error(exc) from exc

        if str(response.status) != "completed":
            raise _response_error(response)
        return GenerationResult(
            text=response.output_text,
            provider_response_id=response.id,
            usage=_usage(response.usage),
        )

    async def stream(
        self,
        request: ProviderRequest,
    ) -> AsyncGenerator[ProviderEvent, None]:
        try:
            stream = await self.client.responses.create(
                **self._request_kwargs(request),
                stream=True,
            )
            try:
                async for event in stream:
                    event_type = event.type
                    if event_type == "response.output_text.delta":
                        yield TextDelta(text=event.delta)
                    elif event_type == "response.refusal.delta":
                        yield RefusalDelta(text=event.delta)
                    elif event_type == "response.completed":
                        yield ProviderCompleted(
                            provider_response_id=event.response.id,
                            usage=_usage(event.response.usage),
                        )
                        return
                    elif event_type in {"response.failed", "response.incomplete"}:
                        raise _response_error(event.response)
                    elif event_type == "error":
                        raise ProviderError(
                            code="provider_stream_error",
                            safe_message="the model provider stream failed",
                            retriable=False,
                        )
                    # Unknown event types are ignored for forward compatibility.
            finally:
                await stream.close()
        except ProviderError:
            raise
        except OpenAIError as exc:
            raise _sdk_error(exc) from exc

        raise ProviderError(
            code="provider_stream_ended",
            safe_message="the model provider stream ended without a terminal event",
            retriable=False,
        )

    async def close(self) -> None:
        await self.client.close()
