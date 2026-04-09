from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import FeatureName, WalletType
from app.core.exceptions import InsufficientCreditsError
from app.core.i18n import t
from app.db.models import FeatureConfig, User
from app.services.ai.router import ModelRouter
from app.services.billing.billing_service import BillingService
from app.services.usage.quota_service import QuotaService
from app.services.ai.antigravity import SafetyBlockedError

logger = logging.getLogger(__name__)


@dataclass
class ImageResult:
    image_bytes: Optional[bytes]
    success: bool
    tokens_used: int = 0
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    quota_limit: Optional[int] = None
    quota_used: Optional[int] = None


class ImageOrchestrator:
    def __init__(self, session: AsyncSession, billing: BillingService, router: ModelRouter, quota_service: QuotaService):
        self.session = session
        self.billing = billing
        self.router = router
        self.quota_service = quota_service

    @staticmethod
    def _is_premium_image_user(user: User) -> bool:
        return user.has_active_vip or user.is_premium or user.vip_credits > 0

    async def _get_feature_config(self) -> FeatureConfig:
        stmt = select(FeatureConfig).where(FeatureConfig.name == FeatureName.IMAGE_GEN)
        config = await self.session.scalar(stmt)
        if not config or not config.is_active:
            raise ValueError("Image feature unavailable")
        return config

    async def process_image_request(self, user_id: int, prompt: str) -> ImageResult:
        user = await self.session.get(User, user_id)
        if not user:
            return ImageResult(image_bytes=None, success=False, error_message=t("en", "errors.user_not_found"), error_code="user_not_found")
        lang = user.language if user and user.language else "fa"
        reference_id = f"img_{uuid.uuid4().hex}"
        premium_user = self._is_premium_image_user(user)
        logger.info("Image request user_id=%s premium=%s", user_id, premium_user)

        try:
            config = await self._get_feature_config()
            cost = int(config.credit_cost or 0)
            if cost <= 0:
                raise ValueError("Invalid image cost config")
        except Exception as exc:
            logger.error("Image config error: %s", exc, exc_info=True)
            return ImageResult(
                image_bytes=None,
                success=False,
                error_message=t(lang, "image.unavailable"),
                error_code="feature_unavailable",
            )

        if not premium_user:
            free_status = await self.quota_service.get_free_image_status_for_user(user.id)
            if free_status.exhausted:
                logger.warning("Free image quota exhausted user_id=%s used=%s limit=%s", user_id, free_status.used, free_status.limit)
                return ImageResult(
                    image_bytes=None,
                    success=False,
                    error_message=t(lang, "image.free_quota_exhausted", limit=free_status.limit),
                    error_code="free_quota_exhausted",
                    quota_limit=free_status.limit,
                    quota_used=free_status.used,
                )

        if premium_user:
            try:
                await self.billing.deduct_credits(
                    user_id=user_id,
                    amount=cost,
                    reference_type="image_generation",
                    reference_id=reference_id,
                    description="AI Image Generation",
                    wallet_type=WalletType.VIP,
                )
            except InsufficientCreditsError:
                await self.session.rollback()
                logger.warning("Image request blocked insufficient VIP credits user_id=%s cost=%s", user_id, cost)
                return ImageResult(
                    image_bytes=None,
                    success=False,
                    error_message=t(lang, "image.insufficient_vip", cost=cost),
                    error_code="insufficient_vip",
                )
            except Exception as exc:
                logger.error("Image billing deduction error: %s", exc, exc_info=True)
                await self.session.rollback()
                return ImageResult(
                    image_bytes=None,
                    success=False,
                    error_message=t(lang, "image.billing_temporary_issue"),
                    error_code="billing_error",
                )

        try:
            image_bytes = await asyncio.wait_for(
                self.router.route_image_request(
                    feature_name=FeatureName.IMAGE_GEN,
                    prompt=prompt,
                ),
                timeout=60.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Image generation timeout for reference_id=%s", reference_id)
            image_bytes = None
            error_message = t(lang, "image.timeout_refunded")
        except SafetyBlockedError as exc:
            logger.warning("Image safety block for user_id=%s category=%s ref=%s", user_id, exc.category, reference_id)
            image_bytes = None
            error_message = t(lang, "abuse.image_content_blocked")
        except Exception as exc:
            logger.error("Image generation failure: %s", exc, exc_info=True)
            image_bytes = None
            error_message = t(lang, "image.failed_refunded")

        if not image_bytes:
            if premium_user:
                try:
                    await self.billing.refund_credits(
                        user_id=user_id,
                        original_reference_id=reference_id,
                        amount=cost,
                        description="Refund: Image generation failed",
                        wallet_type=WalletType.VIP,
                    )
                except Exception as exc:
                    logger.error("Image refund failure for %s: %s", reference_id, exc, exc_info=True)
                    await self.session.rollback()
            return ImageResult(
                image_bytes=None,
                success=False,
                error_message=error_message,
                error_code="generation_failed",
            )

        quota_limit = None
        quota_used = None
        if not premium_user:
            updated_status = await self.quota_service.consume_free_image_for_user(user.id)
            quota_limit = updated_status.limit
            quota_used = updated_status.used
            logger.info("Free image success user_id=%s quota_used=%s/%s", user_id, quota_used, quota_limit)
        else:
            logger.info("Premium image success user_id=%s wallet=vip cost=%s", user_id, cost)

        return ImageResult(
            image_bytes=image_bytes,
            success=True,
            quota_limit=quota_limit,
            quota_used=quota_used,
        )

    async def process_image_edit_request(self, user_id: int, prompt: str, image_bytes: bytes) -> ImageResult:
        """Process an image editing request with billing and weekly quota for free users."""
        user = await self.session.get(User, user_id)
        if not user:
            return ImageResult(image_bytes=None, success=False, error_message=t("en", "errors.user_not_found"), error_code="user_not_found")
        lang = user.language if user and user.language else "fa"
        reference_id = f"imgedit_{uuid.uuid4().hex}"
        premium_user = self._is_premium_image_user(user)
        logger.info("Image edit request user_id=%s premium=%s", user_id, premium_user)

        try:
            stmt = select(FeatureConfig).where(FeatureConfig.name == FeatureName.IMAGE_EDIT)
            config = await self.session.scalar(stmt)
            if not config or not config.is_active:
                raise ValueError("Image edit feature unavailable")
            cost = int(config.credit_cost or 0)
            if cost <= 0:
                raise ValueError("Invalid image edit cost config")
        except Exception as exc:
            logger.error("Image edit config error: %s", exc, exc_info=True)
            return ImageResult(
                image_bytes=None,
                success=False,
                error_message=t(lang, "image.edit_unavailable"),
                error_code="feature_unavailable",
            )

        # ── Free user: weekly quota ──
        if not premium_user:
            free_status = await self.quota_service.get_free_image_edit_status_for_user(user.id)
            if free_status.exhausted:
                logger.warning("Free image edit quota exhausted user_id=%s used=%s limit=%s", user_id, free_status.used, free_status.limit)
                return ImageResult(
                    image_bytes=None,
                    success=False,
                    error_message=t(lang, "image.edit_free_quota_exhausted", limit=free_status.limit),
                    error_code="free_quota_exhausted",
                    quota_limit=free_status.limit,
                    quota_used=free_status.used,
                )

        # ── Premium user: deduct VIP credits ──
        if premium_user:
            try:
                await self.billing.deduct_credits(
                    user_id=user_id,
                    amount=cost,
                    reference_type="image_edit",
                    reference_id=reference_id,
                    description="AI Image Editing",
                    wallet_type=WalletType.VIP,
                )
            except InsufficientCreditsError:
                await self.session.rollback()
                return ImageResult(
                    image_bytes=None,
                    success=False,
                    error_message=t(lang, "image.edit_insufficient_vip", cost=cost),
                    error_code="insufficient_vip",
                )
            except Exception as exc:
                logger.error("Image edit billing error: %s", exc, exc_info=True)
                await self.session.rollback()
                return ImageResult(
                    image_bytes=None,
                    success=False,
                    error_message=t(lang, "image.billing_temporary_issue"),
                    error_code="billing_error",
                )

        # ── Execute image edit via provider ──
        error_message = ""
        try:
            edited_bytes = await asyncio.wait_for(
                self.router.route_image_edit_request(
                    feature_name=FeatureName.IMAGE_EDIT,
                    prompt=prompt,
                    image_bytes=image_bytes,
                ),
                timeout=90.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Image edit timeout for reference_id=%s", reference_id)
            edited_bytes = None
            error_message = t(lang, "image.timeout_refunded")
        except SafetyBlockedError as exc:
            logger.warning("Image edit safety block user_id=%s category=%s ref=%s", user_id, exc.category, reference_id)
            edited_bytes = None
            error_message = t(lang, "abuse.image_content_blocked")
        except Exception as exc:
            logger.error("Image edit failure: %s", exc, exc_info=True)
            edited_bytes = None
            error_message = t(lang, "image.failed_refunded")

        if not edited_bytes:
            if premium_user:
                try:
                    await self.billing.refund_credits(
                        user_id=user_id,
                        original_reference_id=reference_id,
                        amount=cost,
                        description="Refund: Image editing failed",
                        wallet_type=WalletType.VIP,
                    )
                except Exception as exc:
                    logger.error("Image edit refund failure for %s: %s", reference_id, exc, exc_info=True)
                    await self.session.rollback()
            return ImageResult(
                image_bytes=None,
                success=False,
                error_message=error_message,
                error_code="generation_failed",
            )

        # ── Success: consume quota or log ──
        quota_limit = None
        quota_used = None
        if not premium_user:
            updated_status = await self.quota_service.consume_free_image_edit_for_user(user.id)
            quota_limit = updated_status.limit
            quota_used = updated_status.used
            logger.info("Free image edit success user_id=%s quota_used=%s/%s", user_id, quota_used, quota_limit)
        else:
            logger.info("Premium image edit success user_id=%s wallet=vip cost=%s", user_id, cost)

        return ImageResult(
            image_bytes=edited_bytes,
            success=True,
            quota_limit=quota_limit,
            quota_used=quota_used,
        )
