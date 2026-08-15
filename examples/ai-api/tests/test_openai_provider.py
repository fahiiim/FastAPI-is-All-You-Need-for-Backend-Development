from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace

from app.config import ProviderKind, Settings
from app.providers import build_provider
from app.providers.base import ProviderCompleted, ProviderRequest, TextDelta
from app.providers.openai import OpenAIResponsesProvider


def provider_request() -> ProviderRequest:
    return ProviderRequest(
        prompt="environment configured request",
        model="gpt-5-mini",
        instructions="Answer concisely.",
        max_output_tokens=200,
        safety_identifier="hashed-demo-client",
    )


async def test_openai_adapter_is_selected_entirely_from_environment(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AI_API_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("AI_API_DEMO_API_KEY", "env-api-key-0123456789abcdef")
    monkeypatch.setenv(
        "AI_API_IDEMPOTENCY_SECRET",
        "env-idempotency-secret-0123456789abcdef",
    )
    monkeypatch.setenv("AI_API_PROVIDER", "openai")
    monkeypatch.setenv("AI_API_MODEL", "gpt-5-mini")
    monkeypatch.setenv("AI_API_OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("AI_API_PROVIDER_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("AI_API_JOB_LEASE_SECONDS", "10")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    adapter = build_provider(settings)
    try:
        assert settings.provider is ProviderKind.OPENAI
        assert settings.model == "gpt-5-mini"
        assert isinstance(adapter, OpenAIResponsesProvider)
        assert adapter.client.api_key == "test-openai-key"
    finally:
        await adapter.close()


class FakeResponseStream:
    def __init__(self) -> None:
        self.closed = False
        usage = SimpleNamespace(input_tokens=4, output_tokens=2, total_tokens=6)
        response = SimpleNamespace(id="resp_test", usage=usage)
        self.events = [
            SimpleNamespace(type="response.created"),
            SimpleNamespace(type="response.output_text.delta", delta="hello "),
            SimpleNamespace(type="response.output_text.delta", delta="world"),
            SimpleNamespace(type="response.completed", response=response),
        ]

    def __aiter__(self) -> AsyncIterator[object]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[object]:
        for event in self.events:
            yield event

    async def close(self) -> None:
        self.closed = True


class FakeResponsesResource:
    def __init__(self, stream: FakeResponseStream) -> None:
        self.stream = stream
        self.request: dict[str, object] | None = None

    async def create(self, **kwargs: object) -> FakeResponseStream:
        self.request = kwargs
        return self.stream


class FakeOpenAIClient:
    def __init__(self, responses: FakeResponsesResource) -> None:
        self.responses = responses


async def test_openai_stream_maps_responses_api_events_and_closes_stream() -> None:
    stream = FakeResponseStream()
    responses = FakeResponsesResource(stream)
    adapter = object.__new__(OpenAIResponsesProvider)
    adapter.client = FakeOpenAIClient(responses)  # type: ignore[assignment]

    events = [event async for event in adapter.stream(provider_request())]

    assert [event.text for event in events if isinstance(event, TextDelta)] == [
        "hello ",
        "world",
    ]
    completed = events[-1]
    assert isinstance(completed, ProviderCompleted)
    assert completed.provider_response_id == "resp_test"
    assert completed.usage.total_tokens == 6
    assert responses.request == {
        "model": "gpt-5-mini",
        "instructions": "Answer concisely.",
        "input": "environment configured request",
        "max_output_tokens": 200,
        "safety_identifier": "hashed-demo-client",
        "store": False,
        "stream": True,
    }
    assert stream.closed is True
