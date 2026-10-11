"""Central configuration. Values come from environment variables or a local .env file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Repository Fixer - Pipeline"
    environment: str = "development"

    database_url: str = "postgresql+psycopg://repofixer:repofixer@localhost:5432/repofixer"
    valkey_url: str = "valkey://localhost:6379/0"

    github_token: str = ""
    github_webhook_secret: str = ""

    llm_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
