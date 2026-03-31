"""
app/bot/middlewares/db.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
aiogram 3.x outer middleware that injects a scoped database session,
repositories, and orchestrators into every handler call.

Registration::

    from app.bot.middlewares.db import DbSessionMiddleware
    dp.update.outer_middleware(DbSessionMiddleware())
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.db.repositories.chat_repo import ChatRepository
from app.db.session import AsyncSessionLocal
from app.core.access import is_configured_admin

logger = logging.getLogger(__name__)


from app.services.billing.billing_service import BillingService
from app.services.ai.router import ModelRouter
from app.services.chat.memory import MemoryManager
from app.services.queue.queue_service import QueueService
from app.services.chat.orchestrator import ChatOrchestrator
from app.services.chat.image_orchestrator import ImageOrchestrator
from app.services.chat.group_policy import GroupPolicyService
from app.services.search.search_service import SearchService
from app.services.usage.quota_service import QuotaService

class DbSessionMiddleware(BaseMiddleware):
    """Opens an ``AsyncSession`` before the handler runs and guarantees
    it is closed afterwards — regardless of success or failure.

    Injects dependencies into the handler's ``data`` dict:
    * ``session``
    * ``chat_repo``
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
            chat_repo = ChatRepository(session)
            data["chat_repo"] = chat_repo

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
                db_user = await chat_repo.get_or_create_user(
                    telegram_id=user.id,
                    username=user.username,
                    first_name=user.first_name
                )
                expected_admin = is_configured_admin(user.id)
                if db_user.is_admin != expected_admin:
                    db_user.is_admin = expected_admin
                    await session.commit()
                    await session.refresh(db_user)
                data["db_user"] = db_user
                data["is_admin"] = expected_admin

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
            data["group_policy_service"] = GroupPolicyService()
            quota_service = QuotaService(session)
            data["quota_service"] = quota_service
            data["search_service"] = SearchService(session=session, router=router, quota_service=quota_service)

            image_orchestrator = ImageOrchestrator(
                session=session,
                billing=billing,
                router=router,
                quota_service=quota_service,
            )
            data["image_orchestrator"] = image_orchestrator

            logger.debug("DB session opened for update")

            try:
                result = await handler(event, data)
            finally:
                logger.debug("DB session closed for update")

            return result
