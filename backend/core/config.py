"""
Application configuration.
Single source of truth — reads from environment / .env file.
Adheres to SRP: this module ONLY handles settings management.
"""
from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",          # silently skip .env keys not defined in Settings
    )

    # ── Application ────────────────────────────────────────────────────────────
    app_env: str = "development"
    app_debug: bool = True
    secret_key: str = "change-me"

    # ── Database ───────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://escrapper:escrapper_secret@localhost:5432/escrapper_db"

    # ── Redis / Celery ─────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── Celery Beat ────────────────────────────────────────────────────────────
    scrape_cron_hour: int = 0
    scrape_cron_minute: int = 30

    # ── Scraper ────────────────────────────────────────────────────────────────
    epaper_base_url: str = "https://epaper.dailythanthi.com"
    epaper_email: str = ""
    epaper_password: str = ""
    scraper_headless: bool = True
    scraper_timeout_ms: int = 30_000
    scraper_max_retries: int = 3
    scraper_backoff_multiplier: int = 2

    # ── NLP ────────────────────────────────────────────────────────────────────
    summary_max_sentences: int = 3
    dedup_similarity_threshold: float = 0.85

    # ── CORS ───────────────────────────────────────────────────────────────────
    cors_origins: List[str] = ["http://localhost:5173", "http://localhost:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | List[str]) -> List[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()
