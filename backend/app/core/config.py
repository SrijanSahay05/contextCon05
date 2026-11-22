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
    # LLM via OpenRouter (Anthropic key attached there as BYOK); slugs from openrouter.ai/models
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "anthropic/claude-sonnet-5.5"
    llm_fast_model: str = "anthropic/claude-haiku-5.5"
    cache_max_age_hours: int = 24

    # per-run limits
    run_credit_ceiling: float = 300
    run_deadline_minutes: int = 20

    # search relevance
    # Crustdata ranking mode: hybrid (keyword + embedding), lexical or semantic
    search_mode: str = "hybrid"
    # startup gate applied when the query sets no founded year; 0 turns it off
    search_founded_from_year: int = 2016
    # candidates enriched per search (2 credits each), taken after the fit rerank
    search_enrich_cap: int = 15
    # minimum 0-3 fit for a company to pass an explicit concept in the query
    search_concept_min_fit: int = 2

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
