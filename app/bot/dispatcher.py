"""
app/bot/dispatcher.py
~~~~~~~~~~~~~~~~~~~~~~
Factory function that assembles and returns a fully-configured
aiogram ``Dispatcher`` with all middlewares and routers registered.
"""

from __future__ import annotations

from aiogram import Dispatcher

from app.bot.handlers.base import base_router
from app.bot.handlers.chat import chat_router
from app.bot.middlewares.db import DbSessionMiddleware


def get_dispatcher() -> Dispatcher:
    """Create, configure, and return the aiogram Dispatcher.

    Registration order matters:
      1. **Middlewares** – outer middleware runs before any router.
      2. **base_router** – command handlers (``/start``, ``/help``, ``/new``).
      3. **chat_router** – catch-all text handler (must be last so
         commands are matched first).
    """
    dp = Dispatcher()

    # ── Middlewares ────────────────────────────
    # Outer middleware wraps the entire update lifecycle, ensuring
    # every handler receives a fresh DB session + ChatService.
    dp.update.outer_middleware(DbSessionMiddleware())

    # ── Routers (order = priority) ────────────
    dp.include_router(base_router)
    dp.include_router(chat_router)

    return dp
