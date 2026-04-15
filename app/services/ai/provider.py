from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field

@dataclass
class AIMessage:
    role: str  # e.g., 'user', 'model', 'system'
    content: str
    image_bytes: Optional[bytes] = field(default=None, repr=False)
    
@dataclass
class AIResponse:
    text: str
    model_name: str
    tokens_used: int
    finish_reason: str
    raw_metadata: Dict[str, Any]

class BaseAIProvider(ABC):
    """Abstract interface to ensure vendor lock-in prevention and consistent structured AI responses."""
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass

    @abstractmethod
    async def generate_text(
        self, 
        model_name: str, 
        messages: List[AIMessage], 
        system_instruction: Optional[str] = None, 
        max_tokens: Optional[int] = None,
        image_bytes: Optional[bytes] = None,
        **kwargs
    ) -> AIResponse:
        """Generates text from an AI Provider, returning a structured AIResponse.
        
        If image_bytes is provided, the request becomes multimodal (vision):
        the image is sent alongside the last user message for analysis.
        """
        pass

    @abstractmethod
    async def generate_image(self, model_name: str, prompt: str, **kwargs) -> bytes:
        """Generates an image from an AI Provider."""
        pass

    @abstractmethod
    async def edit_image(self, model_name: str, prompt: str, image_bytes: bytes, **kwargs) -> bytes:
        """Edits an existing image using a text instruction."""
        pass
