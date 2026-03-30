import logging
from typing import Dict, List, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models import FeatureConfig
from app.core.enums import FeatureName
from app.services.ai.provider import BaseAIProvider, AIMessage, AIResponse
from app.services.ai.prompt_mgr import PromptBuilder

logger = logging.getLogger(__name__)

def sanitize_telegram_html(text: str) -> str:
    """Sanitization layer to ensure AI model HTML output is legally parseable by Telegram."""
    # This serves as a safety catch. Proper production implementations might regex match supported tags.
    # Telegram supports: <b>, <i>, <u>, <s>, <tg-spoiler>, <a href="...">, <code>, <pre>
    # Note: the PromptBuilder heavily warns the model to behave, but we double-check here.
    return text.replace("**", "<b>").replace("`", "<code>")

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

    async def route_text_request(self, feature_name: FeatureName, prompt: str, history: List[AIMessage], persona: str, language: str) -> AIResponse:
        """Handles text requests enforcing FeatureConfig constraints and fallback policies."""
        config = await self._get_feature_config(feature_name)
        return await self.route_text_request_with_config(config, prompt, history, persona, language)

    async def route_text_request_with_config(self, config: FeatureConfig, prompt: str, history: List[AIMessage], persona: str, language: str) -> AIResponse:
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
                max_tokens=config.max_output_tokens
            )
        except Exception as e:
            # Policy-aware Fallback Logic Evaluation
            if config.fallback_model_name:
                logger.warning(f"Primary model {target_model} failed. Executing fallback policy to {config.fallback_model_name}")
                response = await provider.generate_text(
                    model_name=config.fallback_model_name,
                    messages=messages,
                    system_instruction=system_instruction,
                    max_tokens=config.max_output_tokens
                )
            else:
                logger.error(f"Routing completely failed on model {target_model} with no fallbacks.", exc_info=True)
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
