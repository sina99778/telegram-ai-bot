import logging
import re
from typing import Dict, List, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models import FeatureConfig
from app.core.enums import FeatureName
from app.services.ai.provider import BaseAIProvider, AIMessage, AIResponse
from app.services.ai.prompt_mgr import PromptBuilder

logger = logging.getLogger(__name__)

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")


def sanitize_telegram_html(text: str) -> str:
    """Sanitization layer to ensure AI model HTML output is legally parseable by Telegram."""
    # Convert the markdown patterns we explicitly ask the model for into
    # Telegram-supported HTML while leaving already-valid HTML untouched.
    text = _BOLD_RE.sub(r"<b>\1</b>", text)
    text = _INLINE_CODE_RE.sub(r"<code>\1</code>", text)
    return text

class ModelRouter:
    """
    Policy-aware Router that maps feature requests to the proper AI Providers enforcing configs.
    """
    def __init__(self, session: AsyncSession, providers: Dict[str, BaseAIProvider]):
        self.session = session
        self.providers = providers

    async def _get_feature_config(self, feature_name: FeatureName) -> FeatureConfig:
        stmt = select(FeatureConfig).where(FeatureConfig.name == feature_name)
        config = await self.session.scalar(stmt)
        if not config or not config.is_active:
            raise ValueError(f"Feature '{feature_name.value}' is disabled or missing from configuration.")
        return config

    async def route_text_request(self, feature_name: FeatureName, prompt: str, history: List[AIMessage], persona: str, language: str, *, enable_search: bool = False, image_bytes: bytes | None = None) -> AIResponse:
        """Handles text requests enforcing FeatureConfig constraints and fallback policies."""
        config = await self._get_feature_config(feature_name)
        return await self.route_text_request_with_config(config, prompt, history, persona, language, enable_search=enable_search, image_bytes=image_bytes)

    async def route_text_request_with_config(self, config: FeatureConfig, prompt: str, history: List[AIMessage], persona: str, language: str, *, enable_search: bool = False, image_bytes: bytes | None = None) -> AIResponse:
        """Processes requests utilizing an explicit pre-resolved Configuration object."""
        # 2. Select Provider dynamically
        provider = self.providers.get(config.provider)
        if not provider:
            raise ValueError(f"Provider '{config.provider}' is not registered.")
            
        # 3. Build robust system prompt safely
        system_instruction = PromptBuilder.build_system_prompt(
            persona_key=persona, 
            language=language, 
            feature_context=config.description or ""
        )
        
        # 4. Construct strictly typed message payload
        messages = history + [AIMessage(role="user", content=prompt)]
        
        # 5. Execute via Provider executing robust error fallbacks
        target_model = config.model_name
        try:
            response: AIResponse = await provider.generate_text(
                model_name=target_model,
                messages=messages,
                system_instruction=system_instruction,
                max_tokens=config.max_output_tokens,
                enable_search=enable_search,
                image_bytes=image_bytes,
            )
        except Exception as e:
            # NEVER retry safety-blocked requests on a fallback model
            from app.services.ai.antigravity import SafetyBlockedError
            if isinstance(e, SafetyBlockedError):
                raise

            # Policy-aware Fallback Logic Evaluation
            if config.fallback_model_name:
                logger.error(
                    "Primary model %s failed with error: %s — falling back to %s",
                    target_model,
                    e,
                    config.fallback_model_name,
                    exc_info=True,
                )
                response = await provider.generate_text(
                    model_name=config.fallback_model_name,
                    messages=messages,
                    system_instruction=system_instruction,
                    max_tokens=config.max_output_tokens,
                    enable_search=enable_search,
                    image_bytes=image_bytes,
                )
            else:
                logger.error("Routing completely failed on model %s with no fallbacks.", target_model, exc_info=True)
                raise e

        # 6. Formatting Sanitization
        response.text = sanitize_telegram_html(response.text)
        return response
        
    async def route_image_request(self, feature_name: FeatureName, prompt: str) -> bytes:
        """Handles Image Generation requests via capability-specific provider routing."""
        config = await self._get_feature_config(feature_name)
        
        provider = self.providers.get(config.provider)
        if not provider:
            raise ValueError(f"Provider '{config.provider}' is not registered.")
            
        return await provider.generate_image(model_name=config.model_name, prompt=prompt)

    async def route_image_edit_request(self, feature_name: FeatureName, prompt: str, image_bytes: bytes) -> bytes:
        """Handles Image Editing requests — sends source image + instruction to provider."""
        config = await self._get_feature_config(feature_name)

        provider = self.providers.get(config.provider)
        if not provider:
            raise ValueError(f"Provider '{config.provider}' is not registered.")

        return await provider.edit_image(model_name=config.model_name, prompt=prompt, image_bytes=image_bytes)
