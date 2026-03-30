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


from app.services.billing.billing_service import BillingService
from app.services.ai.router import ModelRouter
from app.services.chat.memory import MemoryManager
from app.services.queue.queue_service import QueueService
from app.services.chat.orchestrator import ChatOrchestrator
from app.services.chat.image_orchestrator import ImageOrchestrator

class DbSessionMiddleware(BaseMiddleware):
    """Opens an ``AsyncSession`` before the handler runs and guarantees
    it is closed afterwards — regardless of success or failure.

    Injects dependencies into the handler's ``data`` dict:
    * ``session``
    * ``chat_service``
    * ``db_user``
    * ``chat_orchestrator``
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        
        async with AsyncSessionLocal() as session:
            data["session"] = session
            chat_service = ChatService(session)
            data["chat_service"] = chat_service

            # 1. Extract the user from the update object
            user = None
            if getattr(event, "message", None):
                user = event.message.from_user
            elif getattr(event, "callback_query", None):
                user = event.callback_query.from_user
            elif getattr(event, "inline_query", None):
                user = event.inline_query.from_user
            elif getattr(event, "from_user", None):
                user = event.from_user

            # 2. Inject db_user if user exists
            if user:
                db_user = await chat_service._repo.get_or_create_user(
                    telegram_id=user.id,
                    username=user.username,
                    first_name=user.first_name
                )
                data["db_user"] = db_user

            # 2. Inject chat_orchestrator locally
            billing = BillingService(session)
            from app.services.ai.antigravity import AntigravityProvider
            router = ModelRouter(session, {"antigravity": AntigravityProvider()})
            memory = MemoryManager(session)
            queue = QueueService()
            chat_orchestrator = ChatOrchestrator(
                session=session,
                billing=billing,
                router=router,
                memory=memory,
                queue_service=queue
            )
            data["chat_orchestrator"] = chat_orchestrator

            image_orchestrator = ImageOrchestrator(
                session=session,
                billing=billing,
                router=router
            )
            data["image_orchestrator"] = image_orchestrator

            logger.debug("DB session opened for update")

            try:
                result = await handler(event, data)
            finally:
                logger.debug("DB session closed for update")

            return result
