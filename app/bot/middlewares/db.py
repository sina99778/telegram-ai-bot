"""
app/bot/middlewares/db.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
aiogram 3.x outer middleware that injects a **scoped database session**
and a ready-to-use **ChatService** instance into every handler call.

Registration::

    from app.bot.middlewares.db import DbSessionMiddleware
    dp.update.outer_middleware(DbSessionMiddleware())
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.db.session import AsyncSessionLocal
from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)


class DbSessionMiddleware(BaseMiddleware):
    """Opens an ``AsyncSession`` before the handler runs and guarantees
    it is closed afterwards — regardless of success or failure.

    Injects two keys into the handler's ``data`` dict:

    * ``session``      – the raw ``AsyncSession``
    * ``chat_service`` – a ``ChatService`` bound to that session
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        """Wrap every incoming update in a database session scope."""

        async with AsyncSessionLocal() as session:
            # Make the session and service available to handlers
            # via keyword injection  (handler(message, session=..., chat_service=...))
            data["session"] = session
            data["chat_service"] = ChatService(session)

            logger.debug("DB session opened for update")

            try:
                result = await handler(event, data)
            finally:
                # AsyncSessionLocal().__aexit__ handles close/rollback,
                # but we log explicitly for observability.
                logger.debug("DB session closed for update")

            return result
