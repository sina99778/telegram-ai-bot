import os
import logging
from typing import List, Dict, Optional, Any
from app.services.ai.provider import BaseAIProvider, AIMessage, AIResponse
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

class AntigravityProvider(BaseAIProvider):
    provider_name = "antigravity"

    def __init__(self):
        self.api_key = os.environ.get("GEMINI_API_KEY")
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

    async def generate_text(
        self, 
        model_name: str, 
        messages: List[AIMessage], 
        system_instruction: Optional[str] = None, 
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> AIResponse:
        if not self.client:
            raise RuntimeError("GEMINI_API_KEY is missing in .env")
            
        contents = []
        for msg in messages:
            role = "user" if msg.role.lower() == "user" else "model"
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg.content)]))

        config = types.GenerateContentConfig()
        if system_instruction:
            config.system_instruction = system_instruction
        if max_tokens:
            config.max_output_tokens = max_tokens

        try:
            response = await self.client.aio.models.generate_content(
                model=model_name,
                contents=contents,
                config=config
            )
            return AIResponse(
                text=response.text or "No response from AI.",
                model_name=model_name,
                tokens_used=0,
                finish_reason="stop",
                raw_metadata={}
            )
        except Exception as e:
            logger.error(f"Gemini API Error: {e}", exc_info=True)
            raise RuntimeError(f"AI Generation failed: {e}")

    async def generate_image(self, model_name: str, prompt: str, **kwargs) -> bytes:
        if not self.client:
            raise RuntimeError("GEMINI_API_KEY is missing")
        try:
            result = await self.client.aio.models.generate_content(
                model='gemini-3-pro-image-preview',
                contents=prompt,
            )
            for candidate in result.candidates:
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if part.inline_data and part.inline_data.data:
                            return part.inline_data.data
            raise RuntimeError("No image data returned")
        except Exception as e:
            logger.error(f"Image Error: {e}", exc_info=True)
            raise RuntimeError("Image generation failed.")
