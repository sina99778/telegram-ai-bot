import logging
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models import Message, Conversation
from app.services.ai.provider import AIMessage

logger = logging.getLogger(__name__)

class TokenEstimator:
    """Replaceable abstraction for token counting. Currently uses text approximations."""
    def estimate_tokens(self, text: str) -> int:
        return int(len(text.split()) * 1.3)

class MemoryManager:
    def __init__(self, session: AsyncSession, tokenizer: Optional[TokenEstimator] = None):
        self.session = session
        self.tokenizer = tokenizer or TokenEstimator()

    async def get_conversation_history(self, conversation_id: int, max_tokens: int = 4000) -> List[AIMessage]:
        """
        Fetches the recent conversation history, ensuring it stays within token limits.
        Reverses the order so the oldest message is first in the list.
        Also logically injects conversation summaries when contextually available.
        """
        # Fetch the conversation to resolve summary state
        conv = await self.session.get(Conversation, conversation_id)
        summary_tokens = 0
        summary_msg = None
        
        if conv and conv.summary_text:
            summary_content = f"Previous conversation summary context: {conv.summary_text}"
            summary_tokens = self.tokenizer.estimate_tokens(summary_content)
            summary_msg = AIMessage(role="system", content=summary_content)
        
        # Calculate remaining tokens for actual messages
        available_tokens = max(0, max_tokens - summary_tokens)

        # Fetch last 20 messages, ordered by newest first
        stmt = select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id.desc()).limit(20)
        result = await self.session.scalars(stmt)
        messages = result.all()
        
        history: List[AIMessage] = []
        current_tokens = 0
        
        for msg in messages:
            estimated_tokens = self.tokenizer.estimate_tokens(msg.content)
            if current_tokens + estimated_tokens > available_tokens:
                logger.info(f"Token limit reached for conversation {conversation_id}. Truncating history.")
                break
                
            # Insert at beginning to maintain chronological order for the AI
            history.insert(0, AIMessage(role=msg.role.value, content=msg.content))
            current_tokens += estimated_tokens
            
        # Prepend the summary if it actively exists
        if summary_msg:
            history.insert(0, summary_msg)
            
        return history
