from __future__ import annotations

import logging
import math
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
from app.services.ai.antigravity import QuotaExhaustedError, SafetyBlockedError
from app.services.config.runtime_config import RuntimeConfig

logger = logging.getLogger(__name__)

SUMMARIZATION_TOKEN_THRESHOLD = 3000
# If a summarization was requested but never finished within this window, treat
# the pending flag as stale and re-enqueue (prevents a permanent latch).
SUMMARIZATION_STALE_SECONDS = 1800


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
        max_tokens: int | None = None,
    ) -> list[AIMessage]:
        """Enforce a hard token ceiling on the context re-sent to the model.

        If the total estimated tokens of *history* + *prompt* exceed
        *max_tokens*, the **oldest non-system** messages are dropped one-by-one
        until the payload fits. This directly bounds input-token cost — the
        single largest line on the provider bill.

        System messages (e.g. conversation summaries injected by
        :class:`MemoryManager`) are always preserved so the model
        retains long-term context even under aggressive trimming.
        """
        if max_tokens is None:
            max_tokens = settings.HISTORY_MAX_TOKENS
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
        normal_cost = await RuntimeConfig.get_int(self.session, "normal_message_cost")
        vip_cost = await RuntimeConfig.get_int(self.session, "vip_message_cost")
        if not allow_vip:
            return RoutedChatPolicy(
                feature_name=FeatureName.FLASH_TEXT,
                wallet_type=WalletType.NORMAL,
                cost=normal_cost,
            )

        requested_is_pro = requested_feature == FeatureName.PRO_TEXT
        has_vip_access = user.has_active_vip
        vip_credits = user.vip_credits

        if requested_is_pro and has_vip_access and vip_credits >= vip_cost:
            return RoutedChatPolicy(
                feature_name=FeatureName.PRO_TEXT,
                wallet_type=WalletType.VIP,
                cost=vip_cost,
            )

        if requested_is_pro and has_vip_access and vip_credits < vip_cost:
            if settings.VIP_DEPLETION_BEHAVIOR == "fallback_to_normal":
                return RoutedChatPolicy(
                    feature_name=FeatureName.FLASH_TEXT,
                    wallet_type=WalletType.NORMAL,
                    cost=normal_cost,
                    depleted_vip_fallback=True,
                    notice=t(lang, "chat.vip_fallback"),
                )
            return RoutedChatPolicy(
                feature_name=FeatureName.PRO_TEXT,
                wallet_type=WalletType.VIP,
                cost=vip_cost,
                notice=t(lang, "chat.vip_depleted"),
            )

        return RoutedChatPolicy(
            feature_name=FeatureName.FLASH_TEXT,
            wallet_type=WalletType.NORMAL,
            cost=normal_cost,
        )

    async def _payg_rate(self, feature_name: FeatureName) -> int:
        """Credits charged per 1000 real tokens for the given text feature."""
        key = "payg_pro_per_1k" if feature_name == FeatureName.PRO_TEXT else "payg_flash_per_1k"
        return await RuntimeConfig.get_int(self.session, key)

    @staticmethod
    def _metered_cost(tokens: int, rate_per_1k: int, min_charge: int) -> int:
        """Round token usage up to whole credits at the given per-1K rate."""
        billed = math.ceil(max(0, tokens) / 1000 * max(0, rate_per_1k))
        return max(min_charge, billed)

    async def _invoke_model(self, config, prompt, history, conversation, image_bytes):
        """Single place the provider is called, shared by flat & PAYG paths."""
        return await self.router.route_text_request_with_config(
            config=config,
            prompt=prompt,
            history=history,
            persona=conversation.persona,
            language=conversation.language_preference,
            image_bytes=image_bytes,
        )

    async def process_message(self, user_id: int, prompt: str, feature_name: FeatureName, allow_vip: bool = True, image_bytes: bytes | None = None, ignore_history: bool = False) -> ChatResult:
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
        is_payg = bool(getattr(user, "payg_enabled", False))

        # Build conversation + history up front. PAYG needs the history to
        # estimate an upper-bound cost before generating; for the flat path it
        # is simply fetched a few lines earlier than before (no behaviour change).
        conversation = await self._get_or_create_active_conversation(user_id, mode_str)
        if ignore_history:
            history = []
        else:
            hist_max_messages = await RuntimeConfig.get_int(self.session, "history_max_messages")
            hist_max_tokens = await RuntimeConfig.get_int(self.session, "history_max_tokens")
            history = await self.memory.get_conversation_history(conversation.id, limit=hist_max_messages)
            # ── Sliding Window Hard Limit (input-token cost control) ──
            # Cap how much prior context is re-sent on every message. Lowering
            # history_max_tokens is the most direct lever on input-token spend.
            history = self._apply_sliding_window(history, prompt, hist_max_tokens)

        if is_payg:
            # ── Pay-as-you-go: charge the REAL token usage after generation ──
            rate = await self._payg_rate(policy.feature_name)
            min_charge = await RuntimeConfig.get_int(self.session, "payg_min_charge")
            est_input = self._tokenizer.estimate_tokens(prompt) + self._tokenizer.estimate_messages(history)
            max_out = config.max_output_tokens or settings.MAX_OUTPUT_TOKENS_PRO
            max_cost = self._metered_cost(est_input + max_out, rate, min_charge)
            balance = user.vip_credits if policy.wallet_type == WalletType.VIP else user.normal_credits
            if balance < max_cost:
                # Reject up-front so usage can never push the wallet negative.
                key = "errors.insufficient_vip" if policy.wallet_type == WalletType.VIP else "errors.insufficient_normal"
                return ChatResult(
                    text=t(lang, key, cost=max_cost),
                    success=False,
                    error_message="insufficient_funds",
                    feature_name=policy.feature_name,
                    wallet_type=policy.wallet_type,
                )
            try:
                # Nothing is deducted yet, so a failure needs no refund.
                response = await self._invoke_model(config, prompt, history, conversation, image_bytes)
            except SafetyBlockedError as exc:
                logger.warning("AI safety block (payg) user_id=%s category=%s ref=%s", user_id, exc.category, reference_id)
                return ChatResult(
                    text=t(lang, "abuse.content_blocked"), success=False, error_message="safety_blocked",
                    feature_name=policy.feature_name, wallet_type=policy.wallet_type,
                )
            except QuotaExhaustedError as exc:
                # Provider out of credits/quota — nothing was charged (PAYG bills
                # after success). Tell the user it's temporary, not their fault.
                logger.error("AI quota exhausted (payg) user_id=%s: %s", user_id, exc)
                return ChatResult(
                    text=t(lang, "errors.service_unavailable"), success=False, error_message="quota_exhausted",
                    feature_name=policy.feature_name, wallet_type=policy.wallet_type,
                )
            except Exception as exc:
                logger.error("AI generation failed (payg): %s", exc, exc_info=True)
                return ChatResult(
                    text=t(lang, "errors.ai_failed_refunded"), success=False, error_message=str(exc),
                    feature_name=policy.feature_name, wallet_type=policy.wallet_type,
                )
            actual_cost = self._metered_cost(response.tokens_used or 0, rate, min_charge)
            actual_cost = min(actual_cost, balance)  # never overdraw
            # Only deduct a positive amount — deduct_credits rejects 0/negative,
            # and a raised+rolled-back deduction here would corrupt the session
            # before the message-persist step below.
            if actual_cost > 0:
                try:
                    await self.billing.deduct_credits(
                        user_id=user_id,
                        amount=actual_cost,
                        reference_type="chat_message_payg",
                        reference_id=reference_id,
                        description=f"PAYG {policy.feature_name.value} {response.tokens_used or 0}tok",
                        wallet_type=policy.wallet_type,
                    )
                except Exception as exc:
                    # Pre-checked balance makes this unlikely; never fail the reply
                    # over a billing hiccup — log and serve the answer.
                    logger.error("PAYG deduction failed ref=%s: %s", reference_id, exc, exc_info=True)
                    await self.session.rollback()
        else:
            # ── Flat per-message: reserve credits before generation, refund on failure ──
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
                response = await self._invoke_model(config, prompt, history, conversation, image_bytes)
            except SafetyBlockedError as exc:
                logger.warning("AI safety block for user_id=%s category=%s ref=%s", user_id, exc.category, reference_id)
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
            except QuotaExhaustedError as exc:
                # Provider out of credits/quota — refund the reserved credits and
                # tell the user it's a temporary service issue (not their wallet).
                logger.error("AI quota exhausted user_id=%s ref=%s: %s", user_id, reference_id, exc)
                await self.session.rollback()
                try:
                    await self.billing.refund_credits(
                        user_id=user_id,
                        original_reference_id=reference_id,
                        amount=cost,
                        description="Refund: AI service quota exhausted",
                        wallet_type=policy.wallet_type,
                    )
                except Exception as refund_exc:
                    logger.error("Quota refund failure for %s: %s", reference_id, refund_exc, exc_info=True)
                    await self.session.rollback()
                return ChatResult(
                    text=t(lang, "errors.service_unavailable"),
                    success=False,
                    error_message="quota_exhausted",
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

        # Re-enqueue if summarization was requested but never completed (e.g. the
        # request was cancelled between the commit and the enqueue, or the worker
        # died) — otherwise the pending flag latches forever and context (and
        # input-token cost) grows unbounded.
        _now = datetime.now(timezone.utc)
        _requested = conversation.summarization_requested_at
        if _requested is not None and _requested.tzinfo is None:
            _requested = _requested.replace(tzinfo=timezone.utc)
        _stale = conversation.summarization_pending and (
            _requested is None or (_now - _requested).total_seconds() > SUMMARIZATION_STALE_SECONDS
        )
        if conversation.total_tokens_used > SUMMARIZATION_TOKEN_THRESHOLD and (
            not conversation.summarization_pending or _stale
        ):
            conversation.summarization_pending = True
            conversation.summarization_requested_at = _now
            await self.session.commit()

            result = await self.queue_service.enqueue_summarization(conversation.id)
            if not result.success:
                conversation.summarization_pending = False
                await self.session.commit()
            else:
                conversation.last_summary_job_id = result.job_id
                await self.session.commit()

        text = response.text.strip() if response.text else ""
        if not text:
            text = t(lang, "chat.empty_response")

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
