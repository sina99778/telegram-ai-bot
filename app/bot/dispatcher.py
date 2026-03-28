from __future__ import annotations

from aiogram import Dispatcher

from app.bot.handlers.base import base_router
from app.bot.handlers.chat import chat_router
from app.bot.handlers.admin import admin_router
from app.bot.middlewares.db import DbSessionMiddleware

def get_dispatcher() -> Dispatcher:
    dp = Dispatcher()

    dp.update.outer_middleware(DbSessionMiddleware())

    dp.include_router(base_router)
    dp.include_router(admin_router)  # Admin commands before catch-all chat
    dp.include_router(chat_router)

    return dp
