import uuid
import logging
import asyncio
from dataclasses import dataclass
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models import FeatureConfig, Message, Conversation
from app.core.enums import FeatureName, MessageRole
from app.core.exceptions import InsufficientCreditsError
from app.services.billing.billing_service import BillingService
from app.services.ai.router import ModelRouter

logger = logging.getLogger(__name__)

@dataclass
class ImageResult:
    image_bytes: Optional[bytes]
    success: bool
    tokens_used: int = 0
    error_message: Optional[str] = None

class ImageOrchestrator:
    def __init__(self, session: AsyncSession, billing: BillingService, router: ModelRouter):
        self.session = session
        self.billing = billing
        self.router = router

    async def _get_feature_config(self) -> FeatureConfig:
        stmt = select(FeatureConfig).where(FeatureConfig.name == FeatureName.IMAGE_GEN)
        config = await self.session.scalar(stmt)
        if not config or not config.is_active:
            raise ValueError("Image generation feature is disabled globally.")
        return config

    async def process_image_request(self, user_id: int, prompt: str) -> ImageResult:
        """
        Executes Queue-ready Image flow securely: 
        Deduct -> Route with Timeout -> Return Bytes -> (Refund on fail).
        """
        reference_id = f"img_{uuid.uuid4().hex}"
        
        # --- Transaction 1: Cost Config & Pre-Deduct ---
        try:
            config = await self._get_feature_config()
            cost = config.credit_cost
            
            await self.billing.deduct_credits(
                user_id=user_id,
                amount=cost,
                reference_type="image_generation",
                reference_id=reference_id,
                description="AI Image Generation"
            )
            await self.session.commit()
        except InsufficientCreditsError:
            await self.session.rollback()
            return ImageResult(image_bytes=None, success=False, error_message=f"❌ Insufficient balance. Generator costs {cost if 'cost' in locals() else 15} credits.")
        except Exception as e:
            logger.error(f"Billing error in image flow: {e}")
            await self.session.rollback()
            return ImageResult(image_bytes=None, success=False, error_message="⚠️ System error checking balance.")

        # --- Generation & Metadata Context (Async Queue Ready) ---
        # The AI execution operates outside lock dependencies using robust timeouts
        image_bytes = None
        try:
            # Explicit timeout limit to prevent permanently hanging workers (e.g. 60 seconds)
            image_bytes = await asyncio.wait_for(
                self.router.route_image_request(
                    feature_name=FeatureName.IMAGE_GEN,
                    prompt=prompt
                ),
                timeout=60.0
            )
        except asyncio.TimeoutError:
            logger.error(f"Image generation timeout for {reference_id}")
            error_msg = "⚠️ The AI ran out of time generating the image. Your credits have been safely refunded."
        except Exception as e:
            logger.error(f"Image Generation critically failed: {e}")
            error_msg = "⚠️ The AI failed to generate the image. Your credits have been refunded."

        # Handle Failures explicitly using Saga Refund Sequence
        if not image_bytes:
            try:
                await self.billing.refund_credits(
                    user_id=user_id,
                    original_reference_id=reference_id,
                    amount=cost,
                    description="Refund: Image Timeout/Failure"
                )
                await self.session.commit()
            except Exception as refund_err:
                logger.error(f"CRITICAL: Image Refund failed for {reference_id}: {refund_err}")
                await self.session.rollback()
            return ImageResult(image_bytes=None, success=False, error_message=error_msg)

        # --- Transaction 2: Persist Metadata for Audit Analytics ---
        try:
            # Store the request purely for analytical inspection
            user_msg = Message(
                conversation_id=None, # System-level standalone message or retrieve default active context
                role=MessageRole.USER, 
                content=f"[IMAGE_REQUEST]: {prompt}",
                tokens_used=cost  # Using credit metric since pure tokens are opaque in image gen
            )
            self.session.add(user_msg)
            await self.session.commit()
        except Exception as db_err:
            logger.error(f"Failed to save image audit metadata: {db_err}")
            await self.session.rollback()
            # Continue safely returning the image despite metadata drop

        return ImageResult(image_bytes=image_bytes, success=True)
