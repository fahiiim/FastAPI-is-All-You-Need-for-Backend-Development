from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import Request

from app.providers.base import (
    LLMProvider,
    ProviderCompleted,
    ProviderError,
    ProviderRequest,
    RefusalDelta,
    TextDelta,
    TokenUsage,
)

logger = logging.getLogger(__name__)


def _usage_payload(usage: TokenUsage) -> dict[str, int | None]:
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
    }


def encode_sse(event: str, data: dict[str, Any]) -> bytes:
    payload = json.dumps(data, ensure_ascii=True, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n".encode()


@dataclass(slots=True)
class StreamLease:
    semaphore: asyncio.Semaphore
    released: bool = False

    async def release(self) -> None:
        if not self.released:
            self.released = True
            self.semaphore.release()


async def generate_sse(
    *,
    request: Request,
    provider: LLMProvider,
    provider_request: ProviderRequest,
    lease: StreamLease,
    max_output_chars: int,
    provider_timeout_seconds: float,
) -> AsyncGenerator[bytes, None]:
    request_id = uuid4().hex
    emitted_chars = 0

    try:
        if await request.is_disconnected():
            return

        yield encode_sse(
            "start",
            {"request_id": request_id, "model": provider_request.model},
        )

        async with asyncio.timeout(provider_timeout_seconds):
            async with aclosing(provider.stream(provider_request)) as events:
                async for event in events:
                    if await request.is_disconnected():
                        logger.info(
                            "SSE client disconnected",
                            extra={"request_id": request_id},
                        )
                        return

                    if isinstance(event, TextDelta):
                        emitted_chars += len(event.text)
                        if emitted_chars > max_output_chars:
                            raise ProviderError(
                                code="stream_output_limit",
                                safe_message=(
                                    "the streamed output exceeded the server limit"
                                ),
                                retriable=False,
                            )
                        yield encode_sse("delta", {"text": event.text})
                    elif isinstance(event, RefusalDelta):
                        emitted_chars += len(event.text)
                        if emitted_chars > max_output_chars:
                            raise ProviderError(
                                code="stream_output_limit",
                                safe_message=(
                                    "the streamed output exceeded the server limit"
                                ),
                                retriable=False,
                            )
                        yield encode_sse("refusal", {"text": event.text})
                    elif isinstance(event, ProviderCompleted):
                        yield encode_sse(
                            "complete",
                            {
                                "provider_response_id": event.provider_response_id,
                                "usage": _usage_payload(event.usage),
                            },
                        )
                        return

        raise ProviderError(
            code="provider_stream_ended",
            safe_message="the model provider stream ended without a terminal event",
            retriable=False,
        )
    except asyncio.CancelledError:
        logger.info("SSE task cancelled", extra={"request_id": request_id})
        raise
    except TimeoutError:
        logger.warning("SSE provider timeout", extra={"request_id": request_id})
        if not await request.is_disconnected():
            yield encode_sse(
                "error",
                {
                    "code": "provider_timeout",
                    "message": "the model provider timed out",
                    "retriable": True,
                },
            )
    except ProviderError as exc:
        logger.warning(
            "SSE provider failure",
            extra={"request_id": request_id, "provider_error_code": exc.code},
        )
        if not await request.is_disconnected():
            error_payload: dict[str, Any] = {
                "code": exc.code,
                "message": exc.safe_message,
                "retriable": exc.retriable,
            }
            if exc.provider_response_id is not None:
                error_payload["provider_response_id"] = exc.provider_response_id
            if exc.usage is not None:
                error_payload["usage"] = _usage_payload(exc.usage)
            yield encode_sse("error", error_payload)
    except Exception:
        logger.exception("Unexpected SSE failure", extra={"request_id": request_id})
        if not await request.is_disconnected():
            yield encode_sse(
                "error",
                {
                    "code": "internal_stream_error",
                    "message": "the stream failed",
                    "retriable": False,
                },
            )
    finally:
        await lease.release()
