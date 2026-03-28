# Telegram AI Bot 🤖

A production-grade Telegram AI assistant powered by **Google Gemini**, built with **FastAPI**, **aiogram 3.x**, and **Clean Architecture**.

## Features

- 🧠 **Google Gemini AI** — Conversational AI via the official `google-genai` SDK
- 💬 **Persistent Conversations** — Full chat history stored in PostgreSQL
- 🔄 **Auto-Retry** — Exponential backoff on transient API failures (429/503)
- 🐳 **Dockerised** — One-command deployment with Docker Compose
- 🔐 **Secure Webhooks** — Secret token verification on every update
- 🏗️ **Clean Architecture** — Repository pattern, service layer, dependency injection

## Architecture

```
app/
├── ai/                    # AI layer
│   ├── client.py          # GeminiClient with retry logic
│   └── prompt_builder.py  # Formats DB history → Gemini API
├── bot/                   # Telegram layer
│   ├── dispatcher.py      # Router & middleware setup
│   ├── handlers/
│   │   ├── base.py        # /start, /help, /new commands
│   │   └── chat.py        # Catch-all text handler
│   └── middlewares/
│       └── db.py          # DB session injection
├── core/                  # Configuration
│   └── config.py          # Pydantic settings
├── db/                    # Database layer
│   ├── models/            # SQLAlchemy ORM models
│   ├── repositories/
│   │   └── chat_repo.py   # Data access (Repository pattern)
│   └── session.py         # Async engine & session factory
├── services/
│   └── chat_service.py    # Business logic orchestrator
└── main.py                # FastAPI entry point + webhook
```

## Quick Start

### 1. Clone & Configure

```bash
git clone https://github.com/YOUR_USERNAME/telegram-ai-bot.git
cd telegram-ai-bot
cp .env.example .env
# Edit .env with your real values
```

### 2. Run with Docker Compose

```bash
docker compose up -d --build
```

### 3. Set up your webhook

The bot automatically registers the webhook on startup using the `WEBHOOK_URL` from your `.env` file.

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `BOT_TOKEN` | Telegram bot token from @BotFather | — |
| `WEBHOOK_URL` | Public HTTPS URL for webhook | — |
| `WEBHOOK_SECRET` | Random string for webhook verification | — |
| `GEMINI_API_KEY` | Google AI API key | — |
| `GEMINI_MODEL` | Gemini model name | `gemini-1.5-pro-latest` |
| `POSTGRES_USER` | Database user | `postgres` |
| `POSTGRES_PASSWORD` | Database password | — |
| `POSTGRES_DB` | Database name | `gemini_bot_db` |
| `POSTGRES_HOST` | Database host | `db` |
| `REDIS_HOST` | Redis host | `redis` |

## Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message & instructions |
| `/help` | Same as /start |
| `/new` | Clear conversation context |

## Tech Stack

- **Python 3.12**
- **FastAPI** — Async web framework
- **aiogram 3.x** — Telegram Bot framework
- **google-genai** — Google Gemini SDK
- **SQLAlchemy 2.0** — Async ORM
- **PostgreSQL 15** — Primary database
- **Redis 7** — Caching (future use)
- **Docker & Docker Compose** — Containerisation
- **tenacity** — Retry logic

## License

MIT
