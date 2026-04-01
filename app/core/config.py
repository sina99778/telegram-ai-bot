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
    BOT_TOKEN: str = ""
    WEBHOOK_URL: str = ""
    WEBHOOK_SECRET: str = ""
    
    # ── Payments ──────────────────────────────
    NOWPAYMENTS_API_KEY: str = ""
    NOWPAYMENTS_IPN_SECRET: str = ""

    # ── Redis (Background ARQ) ────────────────
    REDIS_URL: str = "redis://redis:6379/0"

    # ── Google Gemini AI ──────────────────────
    GEMINI_API_KEY: str = ""
    # Final text models
    GEMINI_MODEL_NORMAL: str = "gemini-3.1-flash-lite-preview"
    GEMINI_MODEL_PRO: str = "gemini-3.1-pro-preview"
    GEMINI_MODEL_IMAGE: str = "gemini-3.1-flash-image-preview"
    NORMAL_MESSAGE_COST: int = 1
    VIP_MESSAGE_COST: int = 1
    VIP_DEPLETION_BEHAVIOR: str = "fallback_to_normal"
    DEFAULT_DAILY_NORMAL_CREDITS: int = 50
    VIP_DEFAULT_PLAN_NAME: str = "vip"
    SEARCH_DAILY_FREE_LIMIT: int = 5
    SEARCH_DAILY_PAID_LIMIT: int = 15
    SEARCH_DAILY_VIP_LIMIT: int = 25
    SEARCH_DAILY_GROUP_LIMIT: int = 7
    FREE_DAILY_IMAGE_LIMIT: int = 5
    PRIVATE_MAX_PROMPT_LENGTH: int = 4000
    SEARCH_MAX_QUERY_LENGTH: int = 500
    IMAGE_MAX_PROMPT_LENGTH: int = 1000
    GROUP_DAILY_GROUP_CAP: int = 150
    GROUP_DAILY_USER_CAP: int = 12
    GROUP_USER_COOLDOWN_SECONDS: int = 15
    GROUP_RESPONSE_TIMEOUT_SECONDS: int = 45
    GROUP_MAX_PROMPT_LENGTH: int = 1000
    PRIVATE_MESSAGE_BURST_LIMIT: int = 6
    PRIVATE_MESSAGE_BURST_WINDOW_SECONDS: int = 30
    SEARCH_COMMAND_COOLDOWN_SECONDS: int = 10
    IMAGE_COMMAND_COOLDOWN_SECONDS: int = 20
    CALLBACK_COOLDOWN_SECONDS: int = 1
    ADMIN_ACTION_COOLDOWN_SECONDS: int = 2
    ABUSE_FAILURE_WINDOW_SECONDS: int = 600
    ABUSE_FAILURE_THRESHOLD: int = 5
    ABUSE_TEMP_BLOCK_SECONDS: int = 600
    WEBHOOK_MAX_BODY_BYTES: int = 262144
    NOWPAYMENTS_WEBHOOK_MAX_BODY_BYTES: int = 131072
    FORCED_JOIN_REQUIRED: bool = False
    FORCED_JOIN_CHANNEL: str = ""
    BROADCAST_BATCH_SIZE: int = 25
    BROADCAST_BATCH_PAUSE_SECONDS: float = 1.5
    BROADCAST_FAILURE_THRESHOLD: int = 50
    BROADCAST_MAX_RECIPIENTS: int = 5000
    SYSTEM_PROMPT: str = "You are a helpful AI assistant."

    # ── PostgreSQL ────────────────────────────
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "postgres"
    POSTGRES_HOST: str = "localhost"

    # ── Admin ─────────────────────────────────
    ADMIN_IDS: str = ""  # Comma-separated Telegram user IDs, e.g. "123456,789012"

    # ── Computed ──────────────────────────────

    @property
    def admin_ids_list(self) -> list[int]:
        """Parse ADMIN_IDS comma-separated string into a list of ints."""
        if not self.ADMIN_IDS:
            return []
        return [int(x.strip()) for x in self.ADMIN_IDS.split(",") if x.strip()]

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
