# Telegram AI Bot

Production-focused Telegram bot built with FastAPI, aiogram, SQLAlchemy, Redis/ARQ, and Gemini.

## Product Rules

- Free users use only `gemini-3.1-flash-lite-preview`
- VIP users can use `gemini-3.1-pro-preview` only if VIP access is active
- Flash-Lite usage consumes `normal_credits`
- Pro usage consumes `vip_credits`
- VIP access is only an unlock flag and does not provide unlimited Pro usage
- If VIP access is active but VIP credits are empty, behavior follows `VIP_DEPLETION_BEHAVIOR`

## Runtime Design

- `BillingService` is the source of truth for wallet mutation and ledger entries
- `ChatOrchestrator` is the source of truth for text model routing and credit deduction
- `ImageOrchestrator` handles image billing/deduction/refund with user-safe messaging
- `ChatRepository` handles user/conversation persistence and daily baseline logic

## Group Rules

- Group chats always use Flash-Lite only
- Group chats never consume `vip_credits`
- Group responses are limited to mention/reply/`/ai` triggers
- Group caps/cooldowns/prompt limits are configurable from env

## Wallet & Purchase UX

Purchases are separated into three clear product types:

- `Normal Credits` packs:
- Adds only `normal_credits`
- Used only for Flash-Lite
- `VIP Credits` packs:
- Adds only `vip_credits`
- Used only for Pro responses
- `VIP Access` packs:
- Extends VIP access duration
- Unlocks Pro mode
- Pro usage still consumes `vip_credits`

Webhook order IDs now carry product metadata and are applied product-by-product instead of using a generic VIP heuristic.

## Bilingual UX

- Persian (`fa`) and English (`en`) are centralized in `app/core/i18n.py`
- `/start` language picker is shown when no language is set yet
- Main menus, wallet/purchase flows, VIP flows, support flows, and group notices are localized

## Admin Panel

Main admin capabilities:

- statistics
- users (search + pagination)
- wallet/VIP adjustments
- gift/discount codes
- broadcast
- pricing inspection

Configured admins in `ADMIN_IDS` automatically see the admin shortcut in the main menu.

## Environment

Copy `.env.example` to `.env` and set real values.

Important keys:

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
- `NOWPAYMENTS_API_KEY=...`

## Migrations

```bash
alembic upgrade head
```

## Verification

```bash
python -m compileall app tests
python -m pytest -q
```
