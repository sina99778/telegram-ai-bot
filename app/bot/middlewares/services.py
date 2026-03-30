from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from app.services.billing.billing_service import BillingService
from app.services.ai.router import ModelRouter
from app.services.chat.memory import MemoryManager
from app.services.chat.orchestrator import ChatOrchestrator
from app.services.chat.image_orchestrator import ImageOrchestrator
from app.services.queue.queue_service import QueueService

class ServicesMiddleware(BaseMiddleware):
    """
    Explicit Dependency Injection Middleware.
    Scaffolds and dynamically attaches robust core Orchestrators safely.
    """
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], providers: Dict):
        self.session_factory = session_factory
        self.providers = providers

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        # Attach explicit safe scoped infrastructure to event mappings
        
        # We spawn stateless instances dynamically linking global factories
        # In a deep production codebase this might utilize mature frameworks (like fast_depends or taskiq)
        # But this explicitly resolves dependency tree requests:
        
        async with self.session_factory() as session:
            billing_service = BillingService(session)
            model_router = ModelRouter(session, self.providers)
            memory_manager = MemoryManager(session)
            queue_service = QueueService()
            
            chat_orchestrator = ChatOrchestrator(
                session_factory=self.session_factory, 
                billing=billing_service, 
                router=model_router, 
                memory=memory_manager,
                queue_service=queue_service
            )
            
            image_orchestrator = ImageOrchestrator(
                session_factory=self.session_factory, 
                billing=billing_service, 
                router=model_router
            )

            data["chat_orchestrator"] = chat_orchestrator
            data["image_orchestrator"] = image_orchestrator
            
            # Continue routing mapping parameters
            return await handler(event, data)
