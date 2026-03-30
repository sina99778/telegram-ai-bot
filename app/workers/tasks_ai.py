import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from app.db.models import Conversation, Message
from app.services.ai.provider import AIMessage

logger = logging.getLogger(__name__)

async def summarize_chat(ctx: dict, conversation_id: int):
    """
    Background job to summarize old messages securely across transactions.
    """
    session_maker: async_sessionmaker[AsyncSession] = ctx['session_maker']
    ai_provider = ctx['providers'].get('antigravity')
    
    if not ai_provider:
        logger.error("AntigravityProvider not found in robust worker context inject.")
        return

    async with session_maker() as session:
        # 1. Fetch conversation reliably
        conv = await session.get(Conversation, conversation_id)
        if not conv:
            logger.error(f"Conversation {conversation_id} not found for summarization.")
            return

        stmt_msgs = select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id.asc())
        messages = (await session.scalars(stmt_msgs)).all()
        
        # 4. Safer Archival Policy: Retain explicitly the last 10 messages untouched
        if len(messages) <= 10:
            return

        # 2. Compile context payload correctly
        chat_text = "\n".join([f"{m.role.value}: {m.content}" for m in messages])
        previous_summary = f"Summary Context:\n{conv.summary_text}\n\n" if conv.summary_text else ""
        
        prompt = (
            f"You are summarizing the following conversation history.\n"
            f"Synthesize the crucial facts, technical parameters, explicit user preferences, and distinct logic context.\n\n"
            f"{previous_summary}---New Messages to Summarize---\n{chat_text}"
        )
        
        # 8. Highly Specific System Prompt eliminating conversational drift
        system_instruction = (
            "You are an expert Conversation Data Aggregator processing raw JSON states. "
            "Your ONLY goal is to output a raw, concise, heavily compressed bulleted summary of all provided payload text. "
            "Do NOT include conversational filler, meta-chatting, or acknowledgement."
        )
        
        try:
            # 5. Guaranteed ACID boundaries implementing Session Begin
            async with session.begin():
                from datetime import datetime, timezone
                conv.summarization_started_at = datetime.now(timezone.utc)
                # 3. Call injected Provider safely executing the flash-lite endpoint dynamically
                response = await ai_provider.generate_text(
                    model_name="gemini-3.1-flash-lite-preview",  # Refined explicit 1. cheap model configuration
                    messages=[AIMessage(role="user", content=prompt)],
                    system_instruction=system_instruction
                )
                
                # 4. Reflect Summary modifications identically
                conv.summary_text = response.text
                conv.summary_version += 1
                
                # Archival Logic: Drop everything safely outside retained horizon
                msgs_to_delete = messages[:-10]
                for m in msgs_to_delete:
                    await session.delete(m)
                    
            logger.info(f"Successfully processed Background summary {conversation_id}. V: {conv.summary_version}")
            
        except Exception as e:
            logger.error(f"Failed completely summarizing conversation {conversation_id}: {e}", exc_info=True)
            # Safe rollback automatically handles inside `Session.begin()` context bounding
        finally:
            async with session.begin():
                clean_conv = await session.get(Conversation, conversation_id)
                if clean_conv:
                    clean_conv.summarization_pending = False
