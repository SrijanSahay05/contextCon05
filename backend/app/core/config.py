from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "contextcon05"
    debug: bool = False

    database_url: str
    mongo_url: str
    mongo_db: str


@lru_cache
def get_settings() -> Settings:
    return Settings()
