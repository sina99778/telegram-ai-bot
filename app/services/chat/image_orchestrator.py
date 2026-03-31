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

logger = logging.getLogger(__name__)


@dataclass
class ImageResult:
    image_bytes: Optional[bytes]
    success: bool
    tokens_used: int = 0
    error_message: Optional[str] = None
    error_code: Optional[str] = None


class ImageOrchestrator:
    def __init__(self, session: AsyncSession, billing: BillingService, router: ModelRouter):
        self.session = session
        self.billing = billing
        self.router = router

    async def _get_feature_config(self) -> FeatureConfig:
        stmt = select(FeatureConfig).where(FeatureConfig.name == FeatureName.IMAGE_GEN)
        config = await self.session.scalar(stmt)
        if not config or not config.is_active:
            raise ValueError("Image feature unavailable")
        return config

    async def process_image_request(self, user_id: int, prompt: str) -> ImageResult:
        user = await self.session.get(User, user_id)
        lang = user.language if user and user.language else "fa"
        reference_id = f"img_{uuid.uuid4().hex}"

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
        except Exception as exc:
            logger.error("Image generation failure: %s", exc, exc_info=True)
            image_bytes = None
            error_message = t(lang, "image.failed_refunded")

        if not image_bytes:
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

        return ImageResult(
            image_bytes=image_bytes,
            success=True,
        )
