import uuid
import logging
from dataclasses import dataclass
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models import Conversation, Message, FeatureConfig
from app.core.enums import FeatureName, MessageRole
from app.core.exceptions import InsufficientCreditsError
from app.services.billing.billing_service import BillingService
from app.services.ai.router import ModelRouter
from app.services.chat.memory import MemoryManager
from app.services.queue.queue_service import QueueService

logger = logging.getLogger(__name__)

# After this many cumulative tokens in a conversation, the orchestrator
# triggers a background summarization job via the QueueService.
SUMMARIZATION_TOKEN_THRESHOLD = 3000

@dataclass
class ChatResult:
    text: str
    success: bool
    model_name: Optional[str] = None
    tokens_used: int = 0
    error_message: Optional[str] = None

class ChatOrchestrator:
    def __init__(self, session: AsyncSession, billing: BillingService, router: ModelRouter, memory: MemoryManager, queue_service: QueueService):
        self.session = session
        self.billing = billing
        self.router = router
        self.memory = memory
        self.queue_service = queue_service

    async def _get_or_create_active_conversation(self, user_id: int, mode_str: str) -> Conversation:
        stmt = select(Conversation).where(
            Conversation.user_id == user_id, 
            Conversation.is_active == True,
            Conversation.conversation_mode == mode_str
        ).order_by(Conversation.created_at.desc()).limit(1)
        
        conv = await self.session.scalar(stmt)
        if not conv:
            conv = Conversation(user_id=user_id, conversation_mode=mode_str)
            self.session.add(conv)
            await self.session.flush()
        return conv

    async def process_message(self, user_id: int, prompt: str, feature_name: FeatureName) -> ChatResult:
        """
        Executes the full pipeline cleanly handling transactions: 
        Deduct -> Route to AI -> Save DB -> (Refund on fail).
        """
        # 1. Fetch Shared Config mapping via Router
        try:
            config = await self.router._get_feature_config(feature_name)
        except Exception as e:
            return ChatResult(text="⚠️ This feature is currently disabled.", success=False, error_message=str(e))
            
        cost = config.credit_cost
        reference_id = f"msg_{uuid.uuid4().hex}"
        mode_str = feature_name.value

        # 2. Pre-deduct credits with explicit commit boundary
        try:
            await self.billing.deduct_credits(
                user_id=user_id,
                amount=cost,
                reference_type="chat_message",
                reference_id=reference_id,
                description=f"AI Chat ({mode_str.upper()})"
            )
            # billing.deduct_credits commits internally (Saga Phase-1).
        except InsufficientCreditsError:
            await self.session.rollback()
            return ChatResult(text=f"❌ Insufficient balance. You need {cost} credits.", success=False, error_message="insufficient_funds")
        except Exception as e:
            logger.error(f"Billing deduction error: {e}")
            await self.session.rollback()
            return ChatResult(text="⚠️ System error checking balance.", success=False, error_message="billing_error")

        # --- A Clean Transaction Context begins for Generation ---

        # 3. Fetch Context & AI Generation
        try:
            conv = await self._get_or_create_active_conversation(user_id, mode_str)
            history = await self.memory.get_conversation_history(conv.id)
            
            # Use Config explicitly mapping
            response = await self.router.route_text_request_with_config(
                config=config,
                prompt=prompt,
                history=history,
                persona=conv.persona,
                language=conv.language_preference
            )
        except Exception as e:
            logger.error(f"AI Generation failed: {e}")
            # Rollback any dirty ORM state (e.g. the new Conversation row).
            # The billing debit is already committed in its own transaction,
            # so the refund below starts a clean compensating transaction.
            await self.session.rollback()
            
            # Saga Refund Execution
            try:
                await self.billing.refund_credits(
                    user_id=user_id,
                    original_reference_id=reference_id,
                    amount=cost,
                    description="Refund: AI Generation Failed"
                )
                await self.session.commit()
            except Exception as refund_err:
                logger.error(f"CRITICAL: Refund failed for {reference_id}: {refund_err}")
                await self.session.rollback()

            return ChatResult(text="⚠️ My AI brain encountered an error. Your credits have been safely refunded.", success=False, error_message=str(e))

        # 4. Save messages metadata persistently
        try:
            tokens_used = response.tokens_used
            
            user_msg = Message(
                conversation_id=conv.id, 
                role=MessageRole.USER, 
                content=prompt,
                tokens_used=tokens_used  # TODO: Use real token count from AIResponse once Gemini SDK exposes usage_metadata
            ) # We record tokens against models predominantly, user estimation as fallback
            
            bot_msg = Message(
                conversation_id=conv.id, 
                role=MessageRole.MODEL, 
                content=response.text,
                tokens_used=tokens_used
            )
            self.session.add_all([user_msg, bot_msg])
            
            conv.total_tokens_used += tokens_used
            conv.last_model_used = response.model_name
            
            await self.session.commit()
        except Exception as e:
            logger.error(f"Failed to persist chat messages for tx {reference_id}: {e}")
            await self.session.rollback()
            # In cases where the AI actually spent the token computing the response successfully,
            # we prioritize returning the successful answer instead of punishing the user explicitly.
            
            
        # 8. SAFE BACKGROUND TRIGGER
        if conv.total_tokens_used > SUMMARIZATION_TOKEN_THRESHOLD and not conv.summarization_pending:
            from datetime import datetime, timezone
            conv.summarization_pending = True
            conv.summarization_requested_at = datetime.now(timezone.utc)
            await self.session.commit() # Commit the flag first
            
            result = await self.queue_service.enqueue_summarization(conv.id)
            if not result.success:
                # Rollback flag if queue fails
                conv.summarization_pending = False
                await self.session.commit()
            else:
                conv.last_summary_job_id = result.job_id
                await self.session.commit()

        return ChatResult(
            text=response.text, 
            success=True, 
            model_name=response.model_name,
            tokens_used=response.tokens_used
        )
