# Telegram AI Bot

Production-focused Telegram bot built with FastAPI, aiogram, SQLAlchemy, Redis/ARQ, and Gemini.

## Product Rules

- Free users use only `gemini-3.1-flash-lite-preview`
- VIP users can use `gemini-3.1-pro-preview` only if VIP access is active
- Flash-Lite usage consumes `normal_credits`
- Pro usage consumes `vip_credits`
- VIP access is only an unlock flag and does not provide unlimited Pro usage
- If VIP access is active but VIP credits are empty, behavior follows `VIP_DEPLETION_BEHAVIOR`
- Normal chat does not auto-run live web search
- Live web search runs only through `/search <query>`
- Default image model is `gemini-3.1-flash-image-preview`
- Free users can generate up to `5` images per day
- Premium/VIP users have no daily image cap, but each image consumes `vip_credits`

## Runtime Design

- `BillingService` is the source of truth for wallet mutation and ledger entries
- `ChatOrchestrator` is the source of truth for text model routing and credit deduction
- `ImageOrchestrator` handles image billing/deduction/refund with user-safe messaging
- `SearchService` is a separate grounded-search path so normal chat and live search stay clearly separated
- `QuotaService` tracks `/search` quotas and free image daily usage
- `AbuseGuardService` adds burst control, temporary cooloffs after repeated failures, and callback throttling
- `ChatRepository` handles user/conversation persistence and daily baseline logic

## Group Rules

- Group chats always use Flash-Lite only
- Group chats never consume `vip_credits`
- Group responses are limited to mention/reply/`/ai` triggers
- Group `/search` works only through the explicit command and has its own daily group quota
- Group caps/cooldowns/prompt limits are configurable from env

## Abuse Prevention Hardening

- Telegram webhook requests are body-size limited and still require `WEBHOOK_SECRET`
- NowPayments IPN requests are body-size limited and can be authenticated with `NOWPAYMENTS_IPN_SECRET`
- Private chat, `/search`, `/image`, callbacks, and admin mutations have cooldown / burst protections
- Abuse throttling is Redis-backed so cooldowns and temporary blocks survive restarts and work across multiple app instances
- Repeated expensive failures can trigger a short temporary block to reduce suspicious retry storms
- Prompt and query lengths are capped before expensive provider calls
- Logs include user/chat/feature/status metadata for billing, search, image, admin actions, and group execution without logging secrets
- Broadcasts run in batches with failure abort protection and an explicit stop control
- Forced-join checks are configuration-driven instead of hardcoded and log operational failures clearly

## Search & Image Policy

- `/search` is the only live-search entry point
- Search quotas:
- Free users: `5/day`
- Paid users: `15/day`
- VIP users: `25/day`
- Groups: `7/day`
- Free image generation: `5/day`
- Premium/VIP image generation: no daily cap, billed from `vip_credits`
- Daily reset is handled through a `feature_usage` table keyed by scope, feature, and reset date

## Wallet & Purchase UX

Purchases are separated into three clear product types:

- `Normal Credits` packs add only `normal_credits` and are used only for Flash-Lite
- `VIP Credits` packs add only `vip_credits` and are used only for Pro responses
- `VIP Access` packs extend VIP access duration, unlock Pro mode, and still require `vip_credits` for actual Pro usage

Webhook order IDs carry product metadata and are applied product-by-product instead of using a generic VIP heuristic.

## Bilingual UX

- Persian (`fa`) and English (`en`) are centralized in `app/core/i18n.py`
- `/start` language picker is shown when no language is set yet
- Main menus, wallet/purchase flows, VIP flows, search help, image help, support flows, and group notices are localized

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
- `GEMINI_MODEL_IMAGE=gemini-3.1-flash-image-preview`
- `NORMAL_MESSAGE_COST=1`
- `VIP_MESSAGE_COST=1`
- `VIP_DEPLETION_BEHAVIOR=fallback_to_normal`
- `DEFAULT_DAILY_NORMAL_CREDITS=50`
- `SEARCH_DAILY_FREE_LIMIT=5`
- `SEARCH_DAILY_PAID_LIMIT=15`
- `SEARCH_DAILY_VIP_LIMIT=25`
- `SEARCH_DAILY_GROUP_LIMIT=7`
- `FREE_DAILY_IMAGE_LIMIT=5`
- `PRIVATE_MAX_PROMPT_LENGTH=4000`
- `SEARCH_MAX_QUERY_LENGTH=500`
- `IMAGE_MAX_PROMPT_LENGTH=1000`
- `GROUP_DAILY_GROUP_CAP=150`
- `GROUP_DAILY_USER_CAP=12`
- `GROUP_USER_COOLDOWN_SECONDS=15`
- `GROUP_RESPONSE_TIMEOUT_SECONDS=45`
- `GROUP_MAX_PROMPT_LENGTH=1000`
- `PRIVATE_MESSAGE_BURST_LIMIT=6`
- `PRIVATE_MESSAGE_BURST_WINDOW_SECONDS=30`
- `SEARCH_COMMAND_COOLDOWN_SECONDS=10`
- `IMAGE_COMMAND_COOLDOWN_SECONDS=20`
- `CALLBACK_COOLDOWN_SECONDS=1`
- `ADMIN_ACTION_COOLDOWN_SECONDS=2`
- `ABUSE_FAILURE_WINDOW_SECONDS=600`
- `ABUSE_FAILURE_THRESHOLD=5`
- `ABUSE_TEMP_BLOCK_SECONDS=600`
- `WEBHOOK_MAX_BODY_BYTES=262144`
- `NOWPAYMENTS_WEBHOOK_MAX_BODY_BYTES=131072`
- `FORCED_JOIN_REQUIRED=false`
- `FORCED_JOIN_CHANNEL=@yourchannel`
- `BROADCAST_BATCH_SIZE=25`
- `BROADCAST_BATCH_PAUSE_SECONDS=1.5`
- `BROADCAST_FAILURE_THRESHOLD=50`
- `BROADCAST_MAX_RECIPIENTS=5000`
- `ADMIN_IDS=123456789,987654321`
- `NOWPAYMENTS_API_KEY=...`
- `NOWPAYMENTS_IPN_SECRET=...`

## Migrations

```bash
alembic upgrade head
```

## Verification

```bash
python -m compileall app tests alembic
python -m pytest -q
```
