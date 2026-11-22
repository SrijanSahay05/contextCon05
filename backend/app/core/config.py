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

    # external data; keys are only needed for live calls, tests use fakes
    crustdata_api_key: str = ""
    crustdata_base_url: str = "https://api.crustdata.com"
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-5-5"
    llm_fast_model: str = "claude-haiku-5-5"
    cache_max_age_hours: int = 24

    # per-run limits
    run_credit_ceiling: float = 300
    run_deadline_minutes: int = 20

    webhook_secret: str = ""

    # Gmail (stretch)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""
    token_encryption_key: str = ""

    dd_reminder_days: int = 5
    dd_timeout_days: int = 14

    upload_dir: str = "./uploads"
    upload_max_mb: int = 25


@lru_cache
def get_settings() -> Settings:
    return Settings()
