"""
app/core/config.py
~~~~~~~~~~~~~~~~~~~
Centralised application settings powered by pydantic-settings.

All values are loaded from environment variables (or a ``.env`` file).
"""

from __future__ import annotations

from pathlib import Path

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

    # ── Mini App (Telegram Web App) ──
    # Public HTTPS URL of the mini app. If empty it is derived from WEBHOOK_URL
    # (same host, /webapp path). The "Open App" button shows only when set.
    WEBAPP_URL: str = ""
    WEBAPP_CHAT_MAX_FILE_BYTES: int = 8 * 1024 * 1024  # 8 MB upload cap
    WEBAPP_INITDATA_MAX_AGE_SECONDS: int = 86400       # reject stale initData (replay)
    
    # ── Payments ──────────────────────────────
    NOWPAYMENTS_API_KEY: str = ""
    NOWPAYMENTS_IPN_SECRET: str = ""

    # ── Redis (Background ARQ) ────────────────
    REDIS_URL: str = "redis://redis:6379/0"

    # ── Google Gemini AI ──────────────────────
    GEMINI_API_KEY: str = ""
    # Final text models
    GEMINI_MODEL_NORMAL: str = "gemini-3.1-flash-lite"  # GA (stable) — same price as the preview
    GEMINI_MODEL_PRO: str = "gemini-3.1-pro-preview"
    GEMINI_MODEL_IMAGE: str = "gemini-3.1-flash-image-preview"
    # ── Per-feature credit costs (calibrated to real provider cost) ──
    # 1 credit ≈ €0.0011 provider cost (one Flash message). Image and Pro are
    # priced to match their true cost so every pack keeps a healthy margin;
    # all are runtime-editable from the admin panel buttons.
    NORMAL_MESSAGE_COST: int = 1       # Flash message  (~€0.0011)
    VIP_MESSAGE_COST: int = 15         # Pro message    (~€0.02, priced conservatively)
    IMAGE_CREDIT_COST: int = 60        # 1 image        (~€0.066)
    IMAGE_EDIT_CREDIT_COST: int = 60
    VIP_DEPLETION_BEHAVIOR: str = "fallback_to_normal"
    # Free tier is intentionally a small "taste" to drive conversion to paid:
    # a few Flash messages a day, no free images (image is a premium feature).
    DEFAULT_DAILY_NORMAL_CREDITS: int = 5
    VIP_DEFAULT_PLAN_NAME: str = "vip"
    # ── Daily usage caps ──────────────────────
    # NOTE: these are the conservative defaults. They are runtime-editable
    # by admins via /setconfig (see app/services/config/runtime_config.py),
    # which overrides them from the bot_settings table without a redeploy.
    SEARCH_DAILY_FREE_LIMIT: int = 1
    SEARCH_DAILY_PAID_LIMIT: int = 8
    SEARCH_DAILY_VIP_LIMIT: int = 15
    SEARCH_DAILY_GROUP_LIMIT: int = 4
    FREE_DAILY_IMAGE_LIMIT: int = 0       # image is a premium (paid) feature
    FREE_WEEKLY_IMAGE_EDIT_LIMIT: int = 0
    IMAGE_EDIT_MAX_PROMPT_LENGTH: int = 500
    IMAGE_EDIT_COMMAND_COOLDOWN_SECONDS: int = 30
    PRIVATE_MAX_PROMPT_LENGTH: int = 4000
    INLINE_MAX_PROMPT_LENGTH: int = 500
    INLINE_DAILY_LIMIT: int = 3
    INLINE_BURST_LIMIT: int = 3
    INLINE_BURST_WINDOW_SECONDS: int = 60
    SEARCH_MAX_QUERY_LENGTH: int = 500
    IMAGE_MAX_PROMPT_LENGTH: int = 1000
    # ── Per-feature output token caps (cost control) ──
    # Output tokens are the expensive half of a request. These hard-cap the
    # model's response length unless an admin raises them via /setconfig.
    MAX_OUTPUT_TOKENS_FLASH: int = 600
    MAX_OUTPUT_TOKENS_PRO: int = 1000

    # ── Pay-as-you-go (token-metered billing) ──
    # Credits charged per 1000 tokens of real usage when a user opts into PAYG.
    # Pro is dearer than Flash, mirroring provider pricing. Tunable via /setconfig.
    PAYG_FLASH_PER_1K: int = 1
    PAYG_PRO_PER_1K: int = 5
    PAYG_MIN_CHARGE: int = 1

    # ── Conversation context size (biggest input-token cost lever) ──
    # How much prior conversation is re-sent to the model on every message.
    # Lower = cheaper input tokens, shorter memory. Tunable via /config buttons.
    HISTORY_MAX_TOKENS: int = 1200
    HISTORY_MAX_MESSAGES: int = 10

    # ── Card-to-card payment (manual admin approval) ──
    CARD_TO_CARD_NUMBER: str = ""
    CARD_TO_CARD_HOLDER: str = ""
    CARD_TO_CARD_NOTE: str = ""
    # Toman per 1 USD, used to show card-to-card amounts in Toman.
    # 0 = not configured (the bot then shows USD only). Admin updates it
    # from the panel button; an optional auto-updater can refresh it too.
    USD_TOMAN_RATE: int = 0

    # ── Live USD→Toman auto-update ──
    # A background task refreshes USD_TOMAN_RATE from a free-market source.
    # On any failure or an out-of-range value, the existing (admin-set) rate
    # is left untouched, so the bot never shows a wrong/zero rate.
    EXCHANGE_RATE_AUTO_ENABLED: bool = True
    # Comma-separated fallback chain: the first source returning a sane value wins.
    # tgju is listed first because it is usually reachable from inside Iran.
    EXCHANGE_RATE_PROVIDER: str = "tgju,bonbast,navasan"
    NAVASAN_API_KEY: str = ""  # optional; navasan source is skipped without it
    EXCHANGE_RATE_UPDATE_INTERVAL_SECONDS: int = 1800  # 30 minutes
    EXCHANGE_RATE_MIN_TOMAN: int = 20000   # sanity floor (reject below)
    EXCHANGE_RATE_MAX_TOMAN: int = 500000  # sanity ceiling (reject above)
    GROUP_DAILY_GROUP_CAP: int = 40
    GROUP_DAILY_USER_CAP: int = 5
    GROUP_USER_COOLDOWN_SECONDS: int = 15
    GROUP_RESPONSE_TIMEOUT_SECONDS: int = 45
    AI_REQUEST_TIMEOUT_SECONDS: int = 60
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
    USER_ANOMALY_WINDOW_SECONDS: int = 300
    USER_ANOMALY_REQUEST_THRESHOLD: int = 30
    GROUP_ANOMALY_WINDOW_SECONDS: int = 300
    GROUP_ANOMALY_REQUEST_THRESHOLD: int = 40
    EXPENSIVE_COMMAND_BURST_WINDOW_SECONDS: int = 180
    EXPENSIVE_COMMAND_BURST_THRESHOLD: int = 4
    CALLBACK_SPAM_WINDOW_SECONDS: int = 60
    CALLBACK_SPAM_THRESHOLD: int = 25
    ANOMALY_CONTAIN_SECONDS: int = 1800
    FEATURE_CONTAIN_SECONDS: int = 900
    WEBHOOK_MAX_BODY_BYTES: int = 262144
    NOWPAYMENTS_WEBHOOK_MAX_BODY_BYTES: int = 131072
    FORCED_JOIN_REQUIRED: bool = False
    FORCED_JOIN_CHANNEL: str = ""
    BROADCAST_BATCH_SIZE: int = 25
    BROADCAST_BATCH_PAUSE_SECONDS: float = 1.5
    BROADCAST_FAILURE_THRESHOLD: int = 50
    BROADCAST_MAX_RECIPIENTS: int = 5000
    BACKUP_ENABLED: bool = False
    # Interval mode: a full backup runs once per BACKUP_INTERVAL_HOURS window
    # (deduped across instances via Redis). BACKUP_SCHEDULE_TIME/TIMEZONE are
    # kept only for the filename timestamp; they no longer gate the schedule.
    BACKUP_INTERVAL_HOURS: int = 12
    BACKUP_SCHEDULE_TIME: str = "03:00"
    BACKUP_TIMEZONE: str = "UTC"
    # After a successful send the local .sql.gz is deleted so the server disk
    # never fills up (the backup lives in Telegram). Retention only caps any
    # leftovers from FAILED sends.
    BACKUP_DELETE_AFTER_SEND: bool = True
    BACKUP_RETENTION_COUNT: int = 3
    BACKUP_DIRECTORY: str = "./backups"
    BACKUP_RECIPIENT_TELEGRAM_ID: int = 0
    BACKUP_PGDUMP_PATH: str = "pg_dump"
    BACKUP_CHECK_INTERVAL_SECONDS: int = 60
    BACKUP_LOCK_SECONDS: int = 3600
    SYSTEM_PROMPT: str = "You are a helpful AI assistant."

    # ── Premium (custom) emoji ──
    # Telegram lets a bot render animated custom emoji ONLY if the bot owner
    # has Telegram Premium. Off by default; when enabled, marked emojis in
    # key messages render as the custom emoji whose id is set in the slots
    # below (admin sets them from the panel). Always falls back to the plain
    # emoji, so nothing breaks when off or for non-premium viewers.
    PREMIUM_EMOJI_ENABLED: bool = False
    CUSTOM_EMOJI_CROWN: str = ""   # 👑
    CUSTOM_EMOJI_COIN: str = ""    # 🪙
    CUSTOM_EMOJI_SPARK: str = ""   # ✨
    CUSTOM_EMOJI_GEM: str = ""     # 💎
    CUSTOM_EMOJI_FIRE: str = ""    # 🔥

    # ── PostgreSQL ────────────────────────────
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "postgres"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    # ── Admin ─────────────────────────────────
    ADMIN_IDS: str = ""  # Comma-separated Telegram user IDs, e.g. "123456,789012"

    # ── Computed ──────────────────────────────

    @property
    def admin_ids_list(self) -> list[int]:
        """Parse ADMIN_IDS comma-separated string into a list of ints.

        Tolerant of a stray non-numeric entry: it's skipped (with a log)
        instead of raising — this property is read on every update via
        is_configured_admin(), so a single typo must not break the whole bot.
        """
        if not self.ADMIN_IDS:
            return []
        ids: list[int] = []
        for part in self.ADMIN_IDS.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ids.append(int(part))
            except ValueError:
                import logging
                logging.getLogger(__name__).warning("Ignoring invalid ADMIN_IDS entry: %r", part)
        return ids

    @property
    def database_url(self) -> str:
        """Build the asyncpg connection string from individual components."""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:"
            f"{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/"
            f"{self.POSTGRES_DB}"
        )

    @property
    def backup_directory_path(self) -> Path:
        return Path(self.BACKUP_DIRECTORY).expanduser()

    @property
    def webapp_url(self) -> str:
        """Public URL of the mini app — explicit WEBAPP_URL, else derived from
        the webhook host (same scheme+host, /webapp path)."""
        if self.WEBAPP_URL:
            return self.WEBAPP_URL.rstrip("/")
        if self.WEBHOOK_URL:
            from urllib.parse import urlsplit, urlunsplit
            p = urlsplit(self.WEBHOOK_URL)
            if p.scheme and p.netloc:
                return urlunsplit((p.scheme, p.netloc, "/webapp", "", ""))
        return ""

    # ── Pydantic configuration ────────────────
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
