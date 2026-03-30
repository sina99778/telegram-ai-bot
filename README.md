# Telegram AI Bot 🤖

A production-grade Telegram AI assistant powered by **Google Gemini**, built with **FastAPI**, **aiogram 3.x**, **credit-based billing**, and **background job processing**.

## Features

- 🧠 **Google Gemini AI** — Multi-model routing (Flash / Pro / Image) via a pluggable provider interface
- 💰 **Credit-Based Billing** — Atomic ledger-audited economy with idempotent deductions, refunds, and admin adjustments
- 💬 **Persistent Conversations** — Full chat history stored in PostgreSQL with automatic background summarization
- 🎨 **AI Image Generation** — `/image` command with Saga-pattern billing (debit → generate → refund on failure)
- 🔄 **Background Workers** — ARQ + Redis for conversation summarization and future async tasks
- 🛡️ **Admin Dashboard** — `/stats`, `/user_info`, `/ledger`, `/grant`, `/setprice` commands
- 🎟️ **Promo & Referral System** — Promo codes, referral rewards, and daily login bonuses
- 💳 **Crypto Payments** — NowPayments IPN webhook for VIP credit purchases
- 🐳 **Dockerised** — One-command deployment with Docker Compose (web + worker + Postgres + Redis)
- 🔐 **Secure Webhooks** — Secret token verification on every Telegram update

## Architecture

```
app/
├── bot/                           # Telegram layer
│   ├── dispatcher.py              # Router & middleware registration
│   ├── handlers/
│   │   ├── admin.py               # Admin-only commands (/stats, /grant, etc.)
│   │   ├── base.py                # /start, /help, /new
│   │   ├── callbacks.py           # Inline keyboard callbacks
│   │   ├── chat.py                # Catch-all text → ChatOrchestrator
│   │   ├── image.py               # /image → ImageOrchestrator
│   │   └── menu.py                # Menu button handlers
│   ├── filters/                   # Custom aiogram filters (e.g. IsAdmin)
│   ├── keyboards/                 # Inline & reply keyboard builders
│   └── middlewares/
│       ├── db.py                  # Session + service injection
│       └── forced_join.py         # Channel membership check
├── core/
│   ├── config.py                  # Pydantic settings (env-driven)
│   ├── enums.py                   # FeatureName, LedgerEntryType, etc.
│   └── exceptions.py             # InsufficientCreditsError, etc.
├── db/
│   ├── models.py                  # SQLAlchemy ORM (User, CreditLedger, etc.)
│   ├── repositories/
│   │   └── chat_repo.py           # Data access layer
│   └── session.py                 # Async engine & session factory
├── services/
│   ├── admin/
│   │   └── admin_service.py       # Admin operations & reporting
│   ├── ai/
│   │   ├── antigravity.py         # Gemini SDK provider implementation
│   │   ├── prompt_mgr.py          # System prompt builder (personas, rules)
│   │   ├── provider.py            # Abstract BaseAIProvider interface
│   │   └── router.py              # Feature → model routing with fallback
│   ├── billing/
│   │   └── billing_service.py     # Atomic credit ops + ledger auditing
│   ├── chat/
│   │   ├── image_orchestrator.py  # Image generation Saga
│   │   ├── memory.py              # Token-bounded context window
│   │   └── orchestrator.py        # Chat Saga (debit → AI → persist)
│   ├── queue/
│   │   ├── job_enqueuer.py        # ARQ connection pool
│   │   └── queue_service.py       # Enqueue facade (decoupled from ARQ)
│   └── payment_service.py         # NowPayments invoice creation
├── workers/
│   ├── main.py                    # ARQ WorkerSettings + startup/shutdown
│   └── tasks_ai.py               # Background summarization task
└── main.py                        # FastAPI entrypoint + webhooks
```

## Core Components

### BillingService
Atomic credit operations with row-level locking (`SELECT ... FOR UPDATE`) and idempotency enforcement via a composite unique index on `(user_id, reference_type, reference_id)`. Every balance mutation produces a `CreditLedger` entry for full audit trail.

### ChatOrchestrator
Implements a Saga pattern for chat: **Phase 1** debits credits (committed before AI call), **Phase 2** calls the AI provider, **Phase 3** persists messages. On AI failure, a compensating `refund_credits` transaction rolls back the debit.

### ImageOrchestrator
Same Saga pattern for image generation with a 60-second async timeout. Uses `FeatureName.IMAGE_GEN` for routing and pricing.

### QueueService
Facade over ARQ that returns structured `JobResult` objects with statuses (`enqueued`, `duplicate`, `failed`). Orchestrators never import ARQ directly.

### AdminService
Read-only reporting (`/stats`) and write operations (`/grant`, `/setprice`) with bounded query limits.

## Quick Start

### 1. Clone & Configure

```bash
git clone https://github.com/sina99778/telegram-ai-bot.git
cd telegram-ai-bot
cp .env.example .env
# Edit .env with your real values
```

### 2. Run with Docker Compose

```bash
docker compose up -d --build
```

This starts four services: PostgreSQL, Redis, the web server (FastAPI + webhook), and the ARQ background worker.

### 3. Webhook

The bot automatically registers its Telegram webhook on startup using the `WEBHOOK_URL` from your `.env` file.

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `BOT_TOKEN` | Telegram bot token from @BotFather | — |
| `WEBHOOK_URL` | Public HTTPS URL for webhook | — |
| `WEBHOOK_SECRET` | Random string for webhook verification | — |
| `GEMINI_API_KEY` | Google AI API key | — |
| `GEMINI_MODEL_NORMAL` | Default (free-tier) model | `gemini-2.5-flash` |
| `GEMINI_MODEL_PRO` | Premium model for VIP users | `gemini-3.1-pro` |
| `POSTGRES_USER` | Database user | `postgres` |
| `POSTGRES_PASSWORD` | Database password | — |
| `POSTGRES_DB` | Database name | `gemini_bot_db` |
| `POSTGRES_HOST` | Database host | `db` |
| `REDIS_URL` | Redis connection URL | `redis://redis:6379/0` |
| `ADMIN_IDS` | Comma-separated admin Telegram user IDs | — |
| `NOWPAYMENTS_API_KEY` | NowPayments API key for crypto payments | — |

## Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message & instructions |
| `/help` | Same as /start |
| `/new` | Clear conversation context |
| `/image <prompt>` | Generate an AI image |
| `/menu` | Interactive menu with model switching |
| `/stats` | *(Admin)* System analytics |
| `/grant <user_id> <amount>` | *(Admin)* Add credits to a user |
| `/setprice <feature> <cost>` | *(Admin)* Update feature pricing |
| `/user_info <user_id>` | *(Admin)* User details |
| `/ledger <user_id>` | *(Admin)* Credit ledger history |

## Testing

### SQLite Integration Tests (`tests/services/`)

Fast logic-validation tests using an in-memory SQLite database. These test BillingService idempotency, orchestrator Saga flows, admin operations, and refund mechanics without needing PostgreSQL.

```bash
pip install -r requirements-test.txt
pytest tests/services/ -v
```

### PostgreSQL Concurrency Tests (`tests/stress/`)

Stress tests that validate `SELECT ... FOR UPDATE` row locking, concurrent credit deduction races, and duplicate webhook idempotency under real PostgreSQL. Requires a running PostgreSQL instance.

```bash
PG_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/test_db \
  pytest tests/stress/ -v
```

These tests are automatically skipped if PostgreSQL is unavailable.

## Tech Stack

- **Python 3.12**
- **FastAPI** — Async web framework
- **aiogram 3.x** — Telegram Bot framework
- **google-genai** — Google Gemini SDK
- **SQLAlchemy 2.0** — Async ORM with row-level locking
- **PostgreSQL 15** — Primary database
- **Redis 7** — Background job queue (ARQ)
- **ARQ** — Async task queue
- **Docker & Docker Compose** — Containerisation
- **pydantic-settings** — Configuration management

## License

MIT
