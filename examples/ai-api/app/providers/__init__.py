from app.config import ProviderKind, Settings
from app.providers.base import LLMProvider
from app.providers.fake import FakeProvider
from app.providers.openai import OpenAIResponsesProvider


def build_provider(settings: Settings) -> LLMProvider:
    if settings.provider is ProviderKind.FAKE:
        return FakeProvider()
    if settings.openai_api_key is None:
        raise RuntimeError("OpenAI provider selected without an API key")
    return OpenAIResponsesProvider(
        api_key=settings.openai_api_key.get_secret_value(),
        timeout_seconds=settings.provider_timeout_seconds,
    )


__all__ = ["LLMProvider", "build_provider"]

