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
- Lightweight anomaly rules detect sustained user/group spikes, expensive command bursts, callback spam, and failure storms
- Anomaly containment can escalate into temporary user/group or feature-specific holds with TTL-based automatic recovery
- Prompt and query lengths are capped before expensive provider calls
- Logs include user/chat/feature/status metadata for billing, search, image, admin actions, and group execution without logging secrets
- Broadcasts run in batches with failure abort protection and an explicit stop control
- Forced-join checks are configuration-driven instead of hardcoded and log operational failures clearly

## Daily Owner Backup

- Daily PostgreSQL backups can run automatically in the app process
- Backups are compressed to `.sql.gz` and sent only to `BACKUP_RECIPIENT_TELEGRAM_ID`
- If no dedicated backup recipient is configured, the first configured admin in `ADMIN_IDS` is used
- Backups use Redis lock/day markers to avoid duplicate sends across multiple instances
- Retention cleanup keeps only the most recent `BACKUP_RETENTION_COUNT` local backup files
- Raw `.env` and other secret files are not included by default

### Restore Guide

Start with a staging or maintenance window first, then restore from a dump like this:

```bash
gunzip -c backup_2026-04-01_03-00.sql.gz | psql -h <host> -p <port> -U <user> -d <database>
```

Always verify the target database before restoring, because the dump is created with `--clean --if-exists`.

## Help UX

- Private chat help is available from `📘 Guide` and `/help`
- Group help is available from `/help` or `/group_help`
- `/search` is the only live web-search entry point
- `/image` explains the free daily image limit for free users and VIP-credit billing for premium usage

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

### Payment methods

Each pack can be paid two ways (chosen on a method screen after tapping a pack):

- **Crypto** — a NowPayments invoice (unchanged).
- **Card-to-card** — the bot shows the destination card (set by an admin from
  **Admin → 🎚 Limits & Prices**, where `card_number` / `card_holder` /
  `card_note` are tappable buttons), the user pays and sends a **photo of the
  receipt**, which creates a *pending* transaction. An admin reviews it under
  **Admin → 💳 Card payments**, sees the receipt, and approves or rejects. On
  approval the pack is granted; the buyer is notified.

Both crypto and card approval funnel through one idempotent fulfillment helper
(`app/services/purchase/fulfillment.py`), so a duplicate IPN or a double admin
tap can never double-credit.

**USD → Toman.** Card-to-card amounts are shown in Toman alongside USD. The
rate is the `usd_toman_rate` button in **Admin → 🎚 Limits & Prices** (Toman
per 1 USD); every pack's Toman price recomputes instantly. Set it to `0` to
show USD only.

A background updater refreshes that rate from a **fallback chain** of
free-market sources (`EXCHANGE_RATE_PROVIDER`, a comma list; default
`tgju,bonbast,navasan`) every `EXCHANGE_RATE_UPDATE_INTERVAL_SECONDS`
(default 30 min). It tries each source in order and applies the first value
that passes a sanity range (`EXCHANGE_RATE_MIN_TOMAN` …
`EXCHANGE_RATE_MAX_TOMAN`); on any failure, parse error, or out-of-range
value it moves to the next source, and if all fail the **admin-set rate is
kept untouched** — the bot never shows a wrong or zero rate.

Built-in sources:

- **tgju** — tgju.org public feed, usually reachable from inside Iran (quotes
  Rial → auto-converted to Toman). Listed first.
- **bonbast** — bonbast.com (no official API; often blocked from Iran).
- **navasan** — paid API quoting Toman directly; set `NAVASAN_API_KEY` to
  enable, otherwise skipped.

Admins can also tap **🔄 Fetch USD→Toman rate now** in the panel to refresh
on demand and see whether any source is reachable. Disable auto-update with
`EXCHANGE_RATE_AUTO_ENABLED=false`. The provider layer
(`app/services/exchange/providers.py`) is pluggable — adding another source
is one more class in the registry.

## Premium (custom) emoji

Telegram renders animated **custom emoji** from a bot only when the **bot
owner has Telegram Premium**. This is therefore opt-in and fully graceful:

- `premium_emoji_enabled` (panel button, default off) — master switch.
- `emoji_crown` / `emoji_coin` / `emoji_spark` / `emoji_gem` / `emoji_fire`
  (panel text settings) — paste the `custom_emoji_id` for 👑/🪙/✨/💎/🔥.

When enabled and a slot has an id, the matching plain emoji is wrapped in
`<tg-emoji emoji-id="…">`. If the owner isn't actually Premium (Telegram
rejects the entity) or the feature is off, the bot transparently falls back
to the plain emoji — it can never break a message
(`app/core/premium_emoji.py`). Currently applied to the `/start` welcome.

## Pricing & margin model

Credit costs are calibrated to the **real provider cost** measured from the
billing export, so every pack keeps a wide margin (target ≥ 70%).

Cost basis (≈ €0.0011 of provider cost per "credit", = one Flash message):

| Feature | Credit cost | ≈ real cost | Notes |
|---|---|---|---|
| Flash message | 1 | €0.0011 | input+output capped |
| Pro message | 15 | ~€0.02 | priced conservatively (Pro ≫ Flash) |
| Image (premium) | 60 | ~€0.066 | from VIP wallet |

Packs (USD list price → margin at worst-case usage):

| Pack | Credits | Price | Margin |
|---|---|---|---|
| Normal 100 | 100 normal | $1.99 | ~94% |
| Normal 350 | 350 normal | $5.99 | ~93% |
| Normal 800 | 800 normal | $11.99 | ~92% |
| VIP 150 | 150 vip | $1.99 | ~91% |
| VIP 700 | 700 vip | $6.99 | ~88% |
| VIP 1800 | 1800 vip | $14.99 | ~86% |
| VIP access 30d / 90d | unlock only | $2.99 / $7.99 | usage billed separately |

Every credit cost (Flash/Pro/image), the daily free allowance, and the output
caps are **runtime-editable from the admin panel buttons**, so margins can be
retuned the moment provider prices move — no redeploy. Pack *list prices* live
in `app/services/purchase/catalog.py`.

## Pay-as-you-go (token-metered) billing

By default every text message costs a flat `NORMAL_MESSAGE_COST` (1 credit).
A user can switch to **pay-as-you-go** from their profile (⚡ button): each
reply is then billed by **real token usage** — `ceil(tokens / 1000 × rate)` —
from the same wallet, with a minimum charge per request. Rates are runtime-editable:

- `payg_flash_per_1k` — credits per 1K Flash tokens (default 1)
- `payg_pro_per_1k` — VIP credits per 1K Pro tokens (default 5)
- `payg_min_charge` — minimum credits per request (default 1)

Safety: before generating, the orchestrator requires the wallet to hold at
least the **maximum possible** cost (estimated input + the model's
`max_output_tokens` cap), so metered usage can never push a balance negative;
the **actual** cost is deducted only after a successful reply, and a failed
generation costs nothing.

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

### Runtime cost controls

Cost-sensitive limits and prices are editable live from Telegram — no redeploy.

**From the admin panel (buttons):** open `/admin` → **🎚 Limits & Prices**.
Each setting is a button showing its current value (★ = overridden); tap one
and send the new number. No need to remember key names.

**From commands (power users):**

```
/config                          # list every editable key with current & default value
/setconfig free_daily_image 1    # e.g. cut free image generations to 1/day
/setconfig search_daily_free 1
/setconfig normal_message_cost 2
/setconfig max_output_tokens_flash 600
```

Both paths write to the same `bot_settings` table, cached for ~30s, falling
back to the env defaults when unset. Editable keys include the per-tier
search limits, free image/edit quotas, inline limit, per-message credit
costs, and the Flash/Pro output-token caps.

### Cost & token notes

- Real Gemini token usage is now captured from `usage_metadata` on every
  call and stored on each conversation, which also drives summarization.
- Text features carry a hard `max_output_tokens` cap (Flash 800, Pro 1500 by
  default) because output tokens are the expensive half of a request.
- The system preamble was compressed (~690 → ~230 tokens) since it ships on
  every single request.
- The biggest per-unit costs are **image generation** and **`/search`
  grounding** — keep their daily caps low and watch the Google Cloud billing
  breakdown by SKU to see where spend actually goes.

## Environment

Copy `.env.example` to `.env` and set real values.

Important keys:

- `GEMINI_MODEL_NORMAL=gemini-3.1-flash-lite` (GA/stable — same price as the preview)
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
- `USER_ANOMALY_WINDOW_SECONDS=300`
- `USER_ANOMALY_REQUEST_THRESHOLD=30`
- `GROUP_ANOMALY_WINDOW_SECONDS=300`
- `GROUP_ANOMALY_REQUEST_THRESHOLD=40`
- `EXPENSIVE_COMMAND_BURST_WINDOW_SECONDS=180`
- `EXPENSIVE_COMMAND_BURST_THRESHOLD=4`
- `CALLBACK_SPAM_WINDOW_SECONDS=60`
- `CALLBACK_SPAM_THRESHOLD=25`
- `ANOMALY_CONTAIN_SECONDS=1800`
- `FEATURE_CONTAIN_SECONDS=900`
- `WEBHOOK_MAX_BODY_BYTES=262144`
- `NOWPAYMENTS_WEBHOOK_MAX_BODY_BYTES=131072`
- `FORCED_JOIN_REQUIRED=false`
- `FORCED_JOIN_CHANNEL=@yourchannel`
- `BROADCAST_BATCH_SIZE=25`
- `BROADCAST_BATCH_PAUSE_SECONDS=1.5`
- `BROADCAST_FAILURE_THRESHOLD=50`
- `BROADCAST_MAX_RECIPIENTS=5000`
- `BACKUP_ENABLED=false`
- `BACKUP_SCHEDULE_TIME=03:00`
- `BACKUP_TIMEZONE=Europe/Berlin`
- `BACKUP_RETENTION_COUNT=7`
- `BACKUP_DIRECTORY=./backups`
- `BACKUP_RECIPIENT_TELEGRAM_ID=123456789`
- `BACKUP_PGDUMP_PATH=pg_dump`
- `BACKUP_CHECK_INTERVAL_SECONDS=60`
- `BACKUP_LOCK_SECONDS=3600`
- `ADMIN_IDS=123456789,987654321`
- `NOWPAYMENTS_API_KEY=...`
- `NOWPAYMENTS_IPN_SECRET=...`
- `POSTGRES_PORT=5432`

## Migrations

```bash
alembic upgrade head
```

## Verification

```bash
python -m compileall app tests alembic
python -m pytest -q
```

## One-shot installer, doctor & interactive menu

The repository ships with `install.sh`, a small bash wrapper around
`docker compose`, `alembic`, and the Telegram API that turns first-time
setup, in-place upgrades, and diagnosis into single commands.

### Interactive mode (default)

Run the script with no arguments to drop into a TUI-style menu with a
live status header (containers, webhook registration, .env readiness):

```bash
./install.sh
```

```
╔══════════════════════════════════════════════════════════════╗
║              Telegram AI Bot — Manager                       ║
║              git: master  e0ca77d                            ║
╠══════════════════════════════════════════════════════════════╣
║  stack:   ● db   ● redis   ● web   ● worker                  ║
║  webhook: registered                                         ║
║  .env:    ready                                              ║
╚══════════════════════════════════════════════════════════════╝

  Setup
   1) ⚙️  .env setup
   2) 🚀  Install                       first-time: build, start, migrate
  Maintenance
   3) 🔄  Update                        git pull + rebuild + migrate
   4) 🩺  Doctor                        11-step diagnosis (read-only)
   5) 🛠  Doctor --fix                  diagnose + safe auto-remediation
  Operations
   6) ⚡  Daily operations >            start, stop, restart, logs, status
   7) 💾  Backup & restore >
   8) 🧰  Advanced >                    shells, migrate, prune, full reset

   9) 📖  Show help
   0) ❌  Exit
```

Sub-menus group the less-frequent actions (per-service log tailing,
backup/restore, container shells, full reset with double confirmation,
…) so the top level stays uncluttered.

### Direct commands

Every action also works headless, which is what `cron`, CI, and remote
shells want:

```bash
./install.sh env-setup     # bootstrap .env from .env.example, auto-generate WEBHOOK_SECRET
$EDITOR .env               # fill in BOT_TOKEN, WEBHOOK_URL, GEMINI_API_KEY, POSTGRES_*
./install.sh install       # build images, start db/redis/web/worker, run migrations, register webhook
./install.sh doctor        # 11-step read-only health check
./install.sh doctor --fix  # safe auto-remediation: regenerate secrets, recreate failed containers,
                           # re-apply migrations, re-register the webhook, prune dangling images
./install.sh update        # git pull + rebuild + migrate, idempotent and data-safe
./install.sh logs worker   # tail any service: web | worker | db | redis
./install.sh backup        # manual gzipped pg_dump into ./backups/
./install.sh status        # compact container + Telegram-webhook summary
./install.sh menu          # explicitly enter the TUI menu
```

`doctor` is a no-side-effects diagnosis by default; `--fix` only applies
non-destructive remediations (it never drops data or removes volumes).
The only menu action that can destroy data is **Advanced → Full reset**,
which requires typing the word `DELETE` to proceed.
