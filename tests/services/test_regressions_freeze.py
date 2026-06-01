"""Regression guards for the 'frozen thinking' chat bug and the stale help text.

The chat froze because the orchestrator called
`memory.get_conversation_history(conversation.id, limit=...)` while the method
had no `limit` parameter → TypeError → unhandled → placeholder never updated.
The help text hard-coded daily limits that drifted from config.
"""

import inspect

import pytest

from app.bot.handlers.menu import _group_help_text, _private_help_text
from app.core.i18n import t
from app.db.models import Conversation, Message
from app.core.enums import MessageRole
from app.services.chat.memory import MemoryManager


def test_memory_history_accepts_limit_and_max_tokens():
    # The orchestrator calls this with a `limit` kwarg — the signature must allow it.
    sig = inspect.signature(MemoryManager.get_conversation_history)
    assert "limit" in sig.parameters
    assert "max_tokens" in sig.parameters


@pytest.mark.asyncio
async def test_memory_history_honours_limit(db_session, setup_base_data):
    conv = Conversation(user_id=setup_base_data["user_id"], conversation_mode="flash")
    db_session.add(conv)
    await db_session.flush()
    for i in range(8):
        db_session.add(Message(conversation_id=conv.id, role=MessageRole.USER, content=f"m{i}"))
    await db_session.commit()

    mem = MemoryManager(db_session)
    history = await mem.get_conversation_history(conv.id, limit=3)
    assert len(history) == 3  # only the 3 most recent loaded


@pytest.mark.parametrize("lang", ["en", "fa"])
def test_help_text_interpolates_live_limits(lang):
    # Must render without KeyError and reflect the passed-in numbers.
    private = _private_help_text(lang, is_admin=False, free_images=1)
    assert "1" in private
    assert "{free_images}" not in private  # placeholder fully substituted

    group = _group_help_text(lang, group_search=4)
    assert "4" in group
    assert "{group_search}" not in group
