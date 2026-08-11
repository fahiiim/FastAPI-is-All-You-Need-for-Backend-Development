from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "postgresql+psycopg://app:app@localhost:5432/app"
    session_ttl_seconds: int = Field(default=3600, ge=300, le=2_592_000)


@lru_cache
def get_settings() -> Settings:
    return Settings()
