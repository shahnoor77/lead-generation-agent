from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Always load .env from repo root (not whatever directory uvicorn was started from).
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    # App
    app_env: str = "development"
    log_level: str = "INFO"

    # LLM — Ollama (local, no API key needed)
    ollama_base_url: str = "http://101.53.238.156:11434"
    # Primary model for structured JSON tasks (ICP scoring, outreach drafts)
    ollama_model: str = "qwen2.5-coder:14b"
    # Lighter model for summarization (faster, cheaper on resources)
    ollama_summarize_model: str = "qwen2.5:1.5b"

    # Database — PostgreSQL
    # Format: postgresql+asyncpg://user:password@host:port/dbname
    database_url: str = "postgresql+asyncpg://leadgen:leadgen@localhost:5432/leadgen"

    # Scraping
    scrape_timeout_seconds: int = 30
    maps_search_region: str = "SA"

    # Sandbox test outreach — disable in production (reject sandbox runs + sandbox inbox APIs).
    sandbox_outreach_enabled: bool = True

    # Auth — shared operator API key (.env) + per-user UUID.
    operator_api_key: str = ""
    allow_user_self_registration: bool = True
    secret_key: str = "change-this-in-production-use-a-long-random-string"


settings = Settings()  # type: ignore[call-arg]
