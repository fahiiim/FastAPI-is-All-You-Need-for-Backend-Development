from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import cast

from fastapi import Request

from app.providers.base import (
    GenerationResult,
    ProviderEvent,
    ProviderRequest,
    TextDelta,
)
from app.providers.fake import FakeBehavior, FakeProvider
from app.sse import StreamLease, generate_sse


def parse_sse(body: str) -> list[tuple[str, dict[str, object]]]:
    parsed: list[tuple[str, dict[str, object]]] = []
    for frame in body.strip().split("\n\n"):
        lines = frame.splitlines()
        event = lines[0].removeprefix("event: ")
        data = json.loads(lines[1].removeprefix("data: "))
        parsed.append((event, data))
    return parsed


async def test_stream_requires_the_documented_api_key(
    app_runner,
    settings_factory,
) -> None:
    async with app_runner(settings_factory()) as harness:
        response = await harness.client.post(
            "/v1/generations:stream",
            json={"prompt": "hello"},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid API credential"}


async def test_fake_stream_has_start_deltas_and_one_complete_terminal_event(
    app_runner,
    settings_factory,
    auth_headers,
) -> None:
    async with app_runner(settings_factory()) as harness:
        response = await harness.client.post(
            "/v1/generations:stream",
            headers=auth_headers,
            json={"prompt": "explain bounded streaming", "max_output_tokens": 20},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    assert events[0][0] == "start"
    assert events[0][1]["model"] == "fake-text-v1"
    assert any(name == "delta" for name, _ in events)
    assert [name for name, _ in events].count("complete") == 1
    assert events[-1][0] == "complete"
    assert events[-1][1]["provider_response_id"].startswith("fake_")
    assert events[-1][1]["usage"] == {
        "input_tokens": 3,
        "output_tokens": 6,
        "total_tokens": 9,
    }


async def test_provider_failure_is_an_error_terminal_event(
    app_runner,
    settings_factory,
    auth_headers,
) -> None:
    provider = FakeProvider(
        FakeBehavior(fail_prompts=frozenset({"fail safely"}))
    )
    async with app_runner(settings_factory(), provider) as harness:
        response = await harness.client.post(
            "/v1/generations:stream",
            headers=auth_headers,
            json={"prompt": "fail safely"},
        )

    events = parse_sse(response.text)
    assert [name for name, _ in events] == ["start", "error"]
    assert events[-1][1] == {
        "code": "fake_provider_failure",
        "message": "the configured fake provider failed",
        "retriable": False,
    }


async def test_stream_timeout_is_an_error_terminal_event(
    app_runner,
    settings_factory,
    auth_headers,
) -> None:
    provider = FakeProvider(FakeBehavior(chunk_delay_seconds=0.05))
    settings = settings_factory(provider_timeout_seconds=0.01)
    async with app_runner(settings, provider) as harness:
        response = await harness.client.post(
            "/v1/generations:stream",
            headers=auth_headers,
            json={"prompt": "too slow"},
        )

    events = parse_sse(response.text)
    assert [name for name, _ in events] == ["start", "error"]
    assert events[-1][1]["code"] == "provider_timeout"
    assert events[-1][1]["retriable"] is True


class DisconnectAwareProvider:
    def __init__(self) -> None:
        self.stream_closed = False

    async def generate(self, request: ProviderRequest) -> GenerationResult:
        raise NotImplementedError

    async def stream(
        self,
        request: ProviderRequest,
    ) -> AsyncGenerator[ProviderEvent, None]:
        try:
            yield TextDelta("this chunk is discarded after disconnect")
        finally:
            self.stream_closed = True

    async def close(self) -> None:
        return None


class DisconnectAfterStart:
    def __init__(self) -> None:
        self.calls = 0

    async def is_disconnected(self) -> bool:
        self.calls += 1
        return self.calls > 1


async def test_disconnect_closes_provider_stream_and_releases_capacity() -> None:
    semaphore = asyncio.Semaphore(1)
    await semaphore.acquire()
    lease = StreamLease(semaphore)
    provider = DisconnectAwareProvider()
    provider_request = ProviderRequest(
        prompt="disconnect",
        model="fake-text-v1",
        instructions="test",
        max_output_tokens=10,
        safety_identifier="test-client-digest",
    )

    chunks = [
        chunk
        async for chunk in generate_sse(
            request=cast(Request, DisconnectAfterStart()),
            provider=provider,
            provider_request=provider_request,
            lease=lease,
            max_output_chars=100,
            provider_timeout_seconds=1,
        )
    ]

    assert len(chunks) == 1
    assert chunks[0].startswith(b"event: start\n")
    assert provider.stream_closed is True
    await asyncio.wait_for(semaphore.acquire(), timeout=0.1)
    semaphore.release()
