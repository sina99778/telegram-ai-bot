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
from app.core.i18n import t
from app.db.models import Conversation, Message, User
from app.services.ai.router import ModelRouter
from app.services.billing.billing_service import BillingService
from app.services.ai.provider import AIMessage
from app.services.chat.memory import MemoryManager, TokenEstimator
from app.services.queue.queue_service import QueueService
from app.services.ai.antigravity import SafetyBlockedError

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
        self._tokenizer = TokenEstimator()

    async def _get_or_create_active_conversation(self, user_id: int, mode_str: str) -> Conversation:
        user = await self.session.get(User, user_id)
        preferred_language = user.language if user and user.language else "fa"
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
            conversation = Conversation(
                user_id=user_id,
                conversation_mode=mode_str,
                language_preference=preferred_language,
            )
            self.session.add(conversation)
            await self.session.flush()
        elif conversation.language_preference != preferred_language:
            conversation.language_preference = preferred_language
        return conversation

    def _apply_sliding_window(
        self,
        history: list[AIMessage],
        prompt: str,
    ) -> list[AIMessage]:
        """Enforce ``PRIVATE_MAX_PROMPT_LENGTH`` as a hard token ceiling.

        If the total estimated tokens of *history* + *prompt* exceed the
        configured maximum, the **oldest non-system** messages are
        dropped one-by-one until the payload fits.

        System messages (e.g. conversation summaries injected by
        :class:`MemoryManager`) are always preserved so the model
        retains long-term context even under aggressive trimming.
        """
        max_tokens = settings.PRIVATE_MAX_PROMPT_LENGTH
        prompt_tokens = self._tokenizer.estimate_tokens(prompt)
        history_tokens = self._tokenizer.estimate_messages(history)
        total_tokens = prompt_tokens + history_tokens

        if total_tokens <= max_tokens:
            return history

        # Separate system messages (index 0 summary) from droppable ones
        system_msgs = [m for m in history if m.role == "system"]
        droppable = [m for m in history if m.role != "system"]
        system_tokens = self._tokenizer.estimate_messages(system_msgs)

        budget = max_tokens - prompt_tokens - system_tokens
        if budget <= 0:
            logger.warning(
                "Sliding window: prompt + system messages already exceed "
                "PRIVATE_MAX_PROMPT_LENGTH (%d). Dropping all history.",
                max_tokens,
            )
            return system_msgs

        # Drop oldest messages first (they're at the front of the list)
        kept: list[AIMessage] = []
        kept_tokens = 0
        for msg in reversed(droppable):
            msg_tokens = self._tokenizer.estimate_tokens(msg.content)
            if kept_tokens + msg_tokens > budget:
                break
            kept.insert(0, msg)
            kept_tokens += msg_tokens

        dropped = len(droppable) - len(kept)
        logger.warning(
            "Sliding window trimmed %d messages  ·  total_before=%d  "
            "total_after=%d  ·  max=%d",
            dropped,
            total_tokens,
            prompt_tokens + system_tokens + kept_tokens,
            max_tokens,
        )
        return system_msgs + kept

    async def _resolve_policy(self, user: User, requested_feature: FeatureName, allow_vip: bool = True) -> RoutedChatPolicy:
        lang = user.language or "fa"
        if not allow_vip:
            return RoutedChatPolicy(
                feature_name=FeatureName.FLASH_TEXT,
                wallet_type=WalletType.NORMAL,
                cost=settings.NORMAL_MESSAGE_COST,
            )

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
                    notice=t(lang, "chat.vip_fallback"),
                )
            return RoutedChatPolicy(
                feature_name=FeatureName.PRO_TEXT,
                wallet_type=WalletType.VIP,
                cost=settings.VIP_MESSAGE_COST,
                notice=t(lang, "chat.vip_depleted"),
            )

        return RoutedChatPolicy(
            feature_name=FeatureName.FLASH_TEXT,
            wallet_type=WalletType.NORMAL,
            cost=settings.NORMAL_MESSAGE_COST,
        )

    async def process_message(self, user_id: int, prompt: str, feature_name: FeatureName, allow_vip: bool = True) -> ChatResult:
        user = await self.session.get(User, user_id)
        if not user:
            return ChatResult(text=t("en", "chat.user_not_found"), success=False, error_message="user_not_found")
        lang = user.language or "fa"
        logger.info(
            "Chat request user_id=%s requested_feature=%s allow_vip=%s prompt_length=%s",
            user_id,
            feature_name.value,
            allow_vip,
            len(prompt),
        )

        policy = await self._resolve_policy(user, feature_name, allow_vip=allow_vip)
        logger.info(
            "Chat policy resolved user_id=%s feature=%s wallet=%s cost=%s",
            user_id,
            policy.feature_name.value,
            policy.wallet_type.value,
            policy.cost,
        )
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
                text=t(lang, "errors.feature_disabled"),
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
            key = "errors.insufficient_vip" if policy.wallet_type == WalletType.VIP else "errors.insufficient_normal"
            return ChatResult(
                text=t(lang, key, cost=cost),
                success=False,
                error_message="insufficient_funds",
                feature_name=policy.feature_name,
                wallet_type=policy.wallet_type,
            )
        except Exception as exc:
            logger.error("Billing deduction error: %s", exc, exc_info=True)
            await self.session.rollback()
            return ChatResult(
                text=t(lang, "errors.wallet_check_failed"),
                success=False,
                error_message="billing_error",
                feature_name=policy.feature_name,
                wallet_type=policy.wallet_type,
            )

        try:
            conversation = await self._get_or_create_active_conversation(user_id, mode_str)
            history = await self.memory.get_conversation_history(conversation.id)

            # ── Sliding Window Hard Limit ─────────────────────────────
            # If the summarization queue is lagging, the history may
            # exceed PRIVATE_MAX_PROMPT_LENGTH.  Drop the oldest non-
            # system messages to stay within the provider envelope.
            history = self._apply_sliding_window(history, prompt)

            response = await self.router.route_text_request_with_config(
                config=config,
                prompt=prompt,
                history=history,
                persona=conversation.persona,
                language=conversation.language_preference,
            )
        except SafetyBlockedError as exc:
            logger.warning(
                "AI safety block for user_id=%s category=%s ref=%s",
                user_id, exc.category, reference_id,
            )
            await self.session.rollback()
            try:
                await self.billing.refund_credits(
                    user_id=user_id,
                    original_reference_id=reference_id,
                    amount=cost,
                    description="Refund: Content blocked by safety filter",
                    wallet_type=policy.wallet_type,
                )
            except Exception as refund_exc:
                logger.error("Safety-block refund failure for %s: %s", reference_id, refund_exc, exc_info=True)
                await self.session.rollback()
            return ChatResult(
                text=t(lang, "abuse.content_blocked"),
                success=False,
                error_message="safety_blocked",
                feature_name=policy.feature_name,
                wallet_type=policy.wallet_type,
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
                text=t(lang, "errors.ai_failed_refunded"),
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
