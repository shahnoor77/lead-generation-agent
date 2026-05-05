from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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

    # Auth — JWT
    secret_key: str = "change-this-in-production-use-a-long-random-string"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24 hours


settings = Settings()  # type: ignore[call-arg]
