from __future__ import annotations

from aiogram import Dispatcher

from app.bot.handlers.base import base_router
from app.bot.handlers.chat import chat_router
from app.bot.handlers.admin import admin_router
from app.bot.handlers.menu import menu_router
from app.bot.handlers.callbacks import callback_router
from app.bot.middlewares.db import DbSessionMiddleware

def get_dispatcher() -> Dispatcher:
    dp = Dispatcher()

    dp.update.outer_middleware(DbSessionMiddleware())

    # Order matters! Specific routers first, general catch-all (chat_router) last.
    dp.include_router(base_router)
    dp.include_router(admin_router)
    dp.include_router(menu_router)      # Intercepts menu button texts
    dp.include_router(callback_router)  # Handles inline button clicks
    dp.include_router(chat_router)      # Sends whatever is left to Gemini

    return dp
