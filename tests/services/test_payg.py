import pytest
from unittest.mock import AsyncMock

from app.core.enums import FeatureName, WalletType
from app.db.models import User
from app.services.billing.billing_service import BillingService
from app.services.chat.memory import MemoryManager
from app.services.chat.orchestrator import ChatOrchestrator
from app.services.config.runtime_config import RuntimeConfig
from app.services.queue.queue_service import JobResult, JobStatus


@pytest.fixture(autouse=True)
def _clear_runtime_cache():
    RuntimeConfig.clear_cache()
    yield
    RuntimeConfig.clear_cache()


def _router(tokens_used: int, max_output_tokens: int = 800):
    router = AsyncMock()
    config = AsyncMock()
    config.credit_cost = 1
    config.max_output_tokens = max_output_tokens  # MUST be a real int for PAYG math
    router._get_feature_config.return_value = config
    response = AsyncMock()
    response.text = "answer"
    response.tokens_used = tokens_used
    response.model_name = "test-model"
    router.route_text_request_with_config.return_value = response
    return router


def _orchestrator(db_session, router):
    billing = BillingService(db_session)
    memory = AsyncMock(spec=MemoryManager)
    memory.get_conversation_history.return_value = []
    queue = AsyncMock()
    # Return a real JobResult so the summarization branch (if the token
    # threshold is crossed) doesn't try to persist an AsyncMock job_id.
    queue.enqueue_summarization.return_value = JobResult(success=False, status=JobStatus.FAILED, job_id=None)
    return ChatOrchestrator(db_session, billing, router, memory, queue)


@pytest.mark.asyncio
async def test_payg_charges_proportional_to_tokens(db_session, setup_base_data):
    user = await db_session.get(User, setup_base_data["user_id"])
    user.payg_enabled = True
    user.normal_credits = 100
    await db_session.commit()

    # rate flash = 1 credit / 1000 tokens; 2000 tokens -> 2 credits
    orch = _orchestrator(db_session, _router(tokens_used=2000))
    res = await orch.process_message(user.id, "hi", FeatureName.FLASH_TEXT)

    assert res.success is True
    refreshed = await db_session.get(User, user.id)
    assert refreshed.normal_credits == 98  # charged exactly 2


@pytest.mark.asyncio
async def test_payg_applies_minimum_charge(db_session, setup_base_data):
    user = await db_session.get(User, setup_base_data["user_id"])
    user.payg_enabled = True
    user.normal_credits = 100
    await db_session.commit()

    # 100 tokens at 1/1k rounds to 0 -> clamped up to min_charge (1)
    orch = _orchestrator(db_session, _router(tokens_used=100))
    res = await orch.process_message(user.id, "hi", FeatureName.FLASH_TEXT)

    assert res.success is True
    refreshed = await db_session.get(User, user.id)
    assert refreshed.normal_credits == 99  # charged the 1-credit minimum


@pytest.mark.asyncio
async def test_payg_rejects_when_balance_below_max_cost(db_session, setup_base_data):
    user = await db_session.get(User, setup_base_data["user_id"])
    user.payg_enabled = True
    user.normal_credits = 0
    await db_session.commit()

    router = _router(tokens_used=500)
    orch = _orchestrator(db_session, router)
    res = await orch.process_message(user.id, "hi", FeatureName.FLASH_TEXT)

    assert res.success is False
    assert res.error_message == "insufficient_funds"
    # The model must NOT be called when the pre-check fails (no free usage).
    router.route_text_request_with_config.assert_not_called()
    refreshed = await db_session.get(User, user.id)
    assert refreshed.normal_credits == 0


@pytest.mark.asyncio
async def test_payg_does_not_charge_on_generation_failure(db_session, setup_base_data):
    user = await db_session.get(User, setup_base_data["user_id"])
    user.payg_enabled = True
    user.normal_credits = 100
    await db_session.commit()

    router = _router(tokens_used=2000)
    router.route_text_request_with_config.side_effect = Exception("provider down")
    orch = _orchestrator(db_session, router)
    res = await orch.process_message(user.id, "hi", FeatureName.FLASH_TEXT)

    assert res.success is False
    refreshed = await db_session.get(User, user.id)
    assert refreshed.normal_credits == 100  # nothing deducted (deduct happens after success)


def test_sliding_window_trims_history_to_token_budget(db_session):
    """The context window cap (the biggest input-token cost lever) must drop
    oldest non-system messages so the payload fits the configured budget."""
    from app.services.ai.provider import AIMessage
    billing = BillingService(db_session)
    memory = AsyncMock(spec=MemoryManager)
    orch = ChatOrchestrator(db_session, billing, AsyncMock(), memory, AsyncMock())

    # 10 messages of ~40 tokens each (~30 words). Budget 100 tokens must keep
    # only the most recent couple, preserving any system summary.
    history = [AIMessage(role="system", content="summary " * 5)]
    history += [AIMessage(role="user", content=("word " * 30)) for _ in range(10)]

    trimmed = orch._apply_sliding_window(history, prompt="hi", max_tokens=100)

    assert trimmed[0].role == "system"          # summary preserved
    assert len(trimmed) < len(history)          # older turns dropped
    total = orch._tokenizer.estimate_messages(trimmed) + orch._tokenizer.estimate_tokens("hi")
    assert total <= 100


@pytest.mark.asyncio
async def test_flat_mode_still_charges_one(db_session, setup_base_data):
    """Regression: a non-PAYG user is still billed the flat per-message cost."""
    user = await db_session.get(User, setup_base_data["user_id"])
    user.payg_enabled = False
    user.normal_credits = 100
    await db_session.commit()

    # 2000 tokens would cost 2 under PAYG; flat must still charge exactly 1.
    orch = _orchestrator(db_session, _router(tokens_used=2000))
    res = await orch.process_message(user.id, "hi", FeatureName.FLASH_TEXT)

    assert res.success is True
    refreshed = await db_session.get(User, user.id)
    assert refreshed.normal_credits == 99  # flat 1, not the metered 2
