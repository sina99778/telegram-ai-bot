# Telegram AI Bot

Production-minded Telegram bot built with FastAPI, aiogram, SQLAlchemy, Redis/ARQ, and Google Gemini.

## Final product rules

- Free users use only `gemini-3.1-flash-lite-preview`
- VIP users unlock `gemini-3.1-pro-preview`
- VIP access only unlocks Pro
- Actual Pro usage still consumes `vip_credits`
- Free usage consumes `normal_credits`
- Default message cost is `1 normal_credit` for Flash-Lite and `1 vip_credit` for Pro
- If VIP access exists but VIP credits are empty, the bot falls back to Flash-Lite when `VIP_DEPLETION_BEHAVIOR=fallback_to_normal`
- Configured admins automatically get an admin shortcut in the main menu
- Group chats always use Flash-Lite only and never consume VIP credits
- Group chats respond only on mention, reply-to-bot, or `/ai`
- Group chats use stricter caps, cooldowns, and prompt-length limits

## Architecture notes

- `BillingService` is the source of truth for wallet mutations, ledger entries, and VIP access granting
- `ChatOrchestrator` is the source of truth for text routing and wallet consumption
- `AdminService` centralizes user management, VIP granting, promo code creation, listing, disabling, and redemption
- `FeatureConfig` still maps features to provider/model configuration
- `credit_balance` remains as a backward-compatible aggregate, but new logic uses `normal_credits` and `vip_credits`

## Data model changes

### User

- `normal_credits`: free wallet
- `vip_credits`: VIP wallet
- `is_vip` + `vip_expire_date`: VIP access state
- `subscription_plan` + `subscription_expires_at`: kept aligned with VIP access

### CreditLedger

- wallet-aware via `wallet_type`

### PromoCode

- `kind`
- `normal_credits`
- `vip_credits`
- `vip_days`
- `discount_percent`
- `max_uses`
- `used_count`
- `max_uses_per_user`
- `is_active`
- `created_by_admin_id`
- `expires_at`

### UserPromo

- tracks per-user usage count per code

## Admin panel

The admin dashboard now supports:

- statistics
- paginated user list
- user search by Telegram ID or username
- per-user actions
- add normal credits
- add VIP credits
- give or extend VIP access
- ban / unban
- create gift / discount codes
- list codes
- disable code
- inspect code usage
- broadcast
- pricing/config inspection

## UI and group UX

- Main menu uses cleaner grouped reply buttons
- Admins see a `🛠 Admin Panel` shortcut automatically when their Telegram ID is in `ADMIN_IDS`
- Profile/VIP/admin inline keyboards now include clearer grouping plus `Back`, `Home`, `Cancel`, and `Refresh` actions where useful
- Group mode is intentionally quieter and more restrictive than private chat

## Environment

## Bilingual onboarding and runtime

- `/start` now shows an inline language picker when the user has no saved language yet
- Major user-facing flows now use centralized translation keys for Persian (`fa`) and English (`en`)
- Runtime request handling is unified around `ChatRepository` and `ChatOrchestrator`; handlers no longer rely on `chat_service._repo`
- Group replies remain free-model only and admin/financial flows stay private-chat oriented

Copy `.env.example` to `.env` and fill in the real values.

Important settings:

- `GEMINI_MODEL_NORMAL=gemini-3.1-flash-lite-preview`
- `GEMINI_MODEL_PRO=gemini-3.1-pro-preview`
- `NORMAL_MESSAGE_COST=1`
- `VIP_MESSAGE_COST=1`
- `VIP_DEPLETION_BEHAVIOR=fallback_to_normal`
- `DEFAULT_DAILY_NORMAL_CREDITS=50`
- `GROUP_DAILY_GROUP_CAP=150`
- `GROUP_DAILY_USER_CAP=12`
- `GROUP_USER_COOLDOWN_SECONDS=20`
- `GROUP_MAX_PROMPT_LENGTH=1000`
- `ADMIN_IDS=123456789,987654321`

## Migrations

Run Alembic after pulling the changes:

```bash
alembic upgrade head
```

The migration upgrades the schema to:

- add `vip_credits`
- backfill data from `premium_credits` when present
- drop `premium_credits` after the backfill
- make ledger entries wallet-aware
- expand promo code metadata
- expand redemption tracking

## Running tests

```bash
python -m pytest -q
```

PostgreSQL stress tests are skipped automatically if PostgreSQL is unreachable.
