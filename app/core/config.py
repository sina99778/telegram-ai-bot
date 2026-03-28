"""
app/core/config.py
~~~~~~~~~~~~~~~~~~~
Centralised application settings powered by pydantic-settings.

All values are loaded from environment variables (or a ``.env`` file).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings — sourced from environment variables.

    The ``database_url`` property constructs a fully-qualified asyncpg
    connection string from the individual Postgres components.
    """

    # ── Telegram Bot ──────────────────────────
    BOT_TOKEN: str
    WEBHOOK_URL: str
    WEBHOOK_SECRET: str

    # ── Google Gemini AI ──────────────────────
    GEMINI_API_KEY: str
    GEMINI_MODEL: str = "gemini-2.5-flash"
    SYSTEM_PROMPT: str = "You are a helpful AI assistant."

    # ── PostgreSQL ────────────────────────────
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_HOST: str

    # ── Computed ──────────────────────────────

    @property
    def database_url(self) -> str:
        """Build the asyncpg connection string from individual components."""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:"
            f"{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:5432/"
            f"{self.POSTGRES_DB}"
        )

    # ── Pydantic configuration ────────────────
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
