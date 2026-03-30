from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import FeatureName, MessageRole, WalletType
from app.core.exceptions import InsufficientCreditsError
from app.db.models import Conversation, Message, User
from app.services.ai.router import ModelRouter
from app.services.billing.billing_service import BillingService
from app.services.chat.memory import MemoryManager
from app.services.queue.queue_service import QueueService

logger = logging.getLogger(__name__)

SUMMARIZATION_TOKEN_THRESHOLD = 3000


@dataclass
class ChatResult:
    text: str
    success: bool
    model_name: Optional[str] = None
    tokens_used: int = 0
    error_message: Optional[str] = None
    feature_name: Optional[FeatureName] = None
    wallet_type: Optional[WalletType] = None


@dataclass
class RoutedChatPolicy:
    feature_name: FeatureName
    wallet_type: WalletType
    cost: int
    depleted_vip_fallback: bool = False
    notice: Optional[str] = None


class ChatOrchestrator:
    def __init__(
        self,
        session: AsyncSession,
        billing: BillingService,
        router: ModelRouter,
        memory: MemoryManager,
        queue_service: QueueService,
    ):
        self.session = session
        self.billing = billing
        self.router = router
        self.memory = memory
        self.queue_service = queue_service

    async def _get_or_create_active_conversation(self, user_id: int, mode_str: str) -> Conversation:
        stmt = (
            select(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.is_active.is_(True),
                Conversation.conversation_mode == mode_str,
            )
            .order_by(Conversation.created_at.desc())
            .limit(1)
        )

        conversation = await self.session.scalar(stmt)
        if not conversation:
            conversation = Conversation(user_id=user_id, conversation_mode=mode_str)
            self.session.add(conversation)
            await self.session.flush()
        return conversation

    async def _resolve_policy(self, user: User, requested_feature: FeatureName) -> RoutedChatPolicy:
        requested_is_pro = requested_feature == FeatureName.PRO_TEXT
        has_vip_access = user.has_active_vip
        vip_credits = user.vip_credits

        if requested_is_pro and has_vip_access and vip_credits >= settings.VIP_MESSAGE_COST:
            return RoutedChatPolicy(
                feature_name=FeatureName.PRO_TEXT,
                wallet_type=WalletType.VIP,
                cost=settings.VIP_MESSAGE_COST,
            )

        if requested_is_pro and has_vip_access and vip_credits < settings.VIP_MESSAGE_COST:
            if settings.VIP_DEPLETION_BEHAVIOR == "fallback_to_normal":
                return RoutedChatPolicy(
                    feature_name=FeatureName.FLASH_TEXT,
                    wallet_type=WalletType.NORMAL,
                    cost=settings.NORMAL_MESSAGE_COST,
                    depleted_vip_fallback=True,
                    notice="VIP credits are finished, so I switched you to Flash-Lite for this message.",
                )
            return RoutedChatPolicy(
                feature_name=FeatureName.PRO_TEXT,
                wallet_type=WalletType.VIP,
                cost=settings.VIP_MESSAGE_COST,
                notice="VIP access is active, but your VIP credits are finished.",
            )

        return RoutedChatPolicy(
            feature_name=FeatureName.FLASH_TEXT,
            wallet_type=WalletType.NORMAL,
            cost=settings.NORMAL_MESSAGE_COST,
        )

    async def process_message(self, user_id: int, prompt: str, feature_name: FeatureName) -> ChatResult:
        user = await self.session.get(User, user_id)
        if not user:
            return ChatResult(text="User not found.", success=False, error_message="user_not_found")

        policy = await self._resolve_policy(user, feature_name)
        if policy.notice and not policy.depleted_vip_fallback and policy.wallet_type == WalletType.VIP:
            return ChatResult(
                text=policy.notice,
                success=False,
                error_message="vip_credits_depleted",
                feature_name=policy.feature_name,
                wallet_type=policy.wallet_type,
            )

        try:
            config = await self.router._get_feature_config(policy.feature_name)
        except Exception as exc:
            return ChatResult(
                text="This feature is currently disabled.",
                success=False,
                error_message=str(exc),
                feature_name=policy.feature_name,
                wallet_type=policy.wallet_type,
            )

        cost = policy.cost
        reference_id = f"msg_{uuid.uuid4().hex}"
        mode_str = policy.feature_name.value

        try:
            await self.billing.deduct_credits(
                user_id=user_id,
                amount=cost,
                reference_type="chat_message",
                reference_id=reference_id,
                description=f"AI Chat ({policy.feature_name.value})",
                wallet_type=policy.wallet_type,
            )
        except InsufficientCreditsError:
            await self.session.rollback()
            wallet_name = "VIP" if policy.wallet_type == WalletType.VIP else "normal"
            return ChatResult(
                text=f"Insufficient balance in your {wallet_name} wallet. You need {cost} credits.",
                success=False,
                error_message="insufficient_funds",
                feature_name=policy.feature_name,
                wallet_type=policy.wallet_type,
            )
        except Exception as exc:
            logger.error("Billing deduction error: %s", exc, exc_info=True)
            await self.session.rollback()
            return ChatResult(
                text="System error checking wallet balance.",
                success=False,
                error_message="billing_error",
                feature_name=policy.feature_name,
                wallet_type=policy.wallet_type,
            )

        try:
            conversation = await self._get_or_create_active_conversation(user_id, mode_str)
            history = await self.memory.get_conversation_history(conversation.id)
            response = await self.router.route_text_request_with_config(
                config=config,
                prompt=prompt,
                history=history,
                persona=conversation.persona,
                language=conversation.language_preference,
            )
        except Exception as exc:
            logger.error("AI generation failed: %s", exc, exc_info=True)
            await self.session.rollback()
            try:
                await self.billing.refund_credits(
                    user_id=user_id,
                    original_reference_id=reference_id,
                    amount=cost,
                    description="Refund: AI generation failed",
                    wallet_type=policy.wallet_type,
                )
            except Exception as refund_exc:
                logger.error("Critical refund failure for %s: %s", reference_id, refund_exc, exc_info=True)
                await self.session.rollback()

            return ChatResult(
                text="My AI brain encountered an error and your credits were refunded.",
                success=False,
                error_message=str(exc),
                feature_name=policy.feature_name,
                wallet_type=policy.wallet_type,
            )

        try:
            user_message = Message(
                conversation_id=conversation.id,
                role=MessageRole.USER,
                content=prompt,
                tokens_used=response.tokens_used,
            )
            model_message = Message(
                conversation_id=conversation.id,
                role=MessageRole.MODEL,
                content=response.text,
                tokens_used=response.tokens_used,
            )
            self.session.add_all([user_message, model_message])

            conversation.total_tokens_used += response.tokens_used
            conversation.last_model_used = response.model_name
            await self.session.commit()
        except Exception as exc:
            logger.error("Failed to persist chat messages for %s: %s", reference_id, exc, exc_info=True)
            await self.session.rollback()

        if conversation.total_tokens_used > SUMMARIZATION_TOKEN_THRESHOLD and not conversation.summarization_pending:
            conversation.summarization_pending = True
            conversation.summarization_requested_at = datetime.now(timezone.utc)
            await self.session.commit()

            result = await self.queue_service.enqueue_summarization(conversation.id)
            if not result.success:
                conversation.summarization_pending = False
                await self.session.commit()
            else:
                conversation.last_summary_job_id = result.job_id
                await self.session.commit()

        text = response.text
        if policy.notice and policy.depleted_vip_fallback:
            text = f"{policy.notice}\n\n{text}"

        return ChatResult(
            text=text,
            success=True,
            model_name=response.model_name,
            tokens_used=response.tokens_used,
            feature_name=policy.feature_name,
            wallet_type=policy.wallet_type,
        )
