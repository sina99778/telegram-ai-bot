import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy import select
from app.services.chat.orchestrator import ChatOrchestrator, ChatResult
from app.services.chat.memory import MemoryManager
from app.services.billing.billing_service import BillingService
from app.db.models import Conversation, User
from app.core.enums import FeatureName
from app.services.queue.queue_service import JobResult, JobStatus

@pytest.fixture
def session_factory(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)

@pytest.fixture
def mock_router():
    router = AsyncMock()
    # Mock Config lookup internal explicitly binding return object natively
    config_mock = AsyncMock()
    config_mock.credit_cost = 1
    router._get_feature_config.return_value = config_mock
    
    # Mock Text Response
    response = AsyncMock()
    response.text = "Mock AI Response"
    response.tokens_used = 150
    response.model_name = "test-model"
    router.route_text_request_with_config.return_value = response
    return router

@pytest.mark.asyncio
async def test_orchestrator_queue_trigger(db_session, session_factory, setup_base_data, mock_router):
    # Base Orchestrator Setup
    billing = BillingService(db_session)
    memory = AsyncMock(spec=MemoryManager)
    memory.get_conversation_history.return_value = []
    
    queue_service = AsyncMock()
    queue_service.enqueue_summarization.return_value = JobResult(success=True, status=JobStatus.ENQUEUED, job_id="test_job_123")
    
    orchestrator = ChatOrchestrator(db_session, billing, mock_router, memory, queue_service)
    user_id = setup_base_data["user_id"]
    
    # 6. Do not rely on massive prompt string. Pre-set Conversation Token State cleanly.
    conv = Conversation(user_id=user_id, conversation_mode=FeatureName.FLASH_TEXT.value, total_tokens_used=3500)
    db_session.add(conv)
    await db_session.commit()
    
    # Action execution
    response = await orchestrator.process_message(user_id=user_id, prompt="Hello", feature_name=FeatureName.FLASH_TEXT)
    
    assert response.success is True
    assert response.text == "Mock AI Response"
    
    # Verify Queue Trigger was universally initiated
    queue_service.enqueue_summarization.assert_called_once_with(conv.id)
    
    # Verify DB Flag applied accurately
    refreshed_conv = await db_session.get(Conversation, conv.id)
    assert refreshed_conv.summarization_pending is True
    assert refreshed_conv.last_summary_job_id == "test_job_123"

# 7. Add extreme edge condition handlers ensuring refund scopes work natively
@pytest.mark.asyncio
async def test_orchestrator_insufficient_balance(db_session, setup_base_data, mock_router):
    billing = AsyncMock()
    memory = AsyncMock()
    queue = AsyncMock()
    
    orchestrator = ChatOrchestrator(db_session, billing, mock_router, memory, queue)
    
    # Emulate User having zero balance mapping natively
    from app.core.exceptions import InsufficientCreditsError
    billing.deduct_credits.side_effect = InsufficientCreditsError(required=1, available=0)
    
    res = await orchestrator.process_message(setup_base_data["user_id"], "hi", FeatureName.FLASH_TEXT)
    assert res.success is False
    assert "not have enough normal credits" in res.text

@pytest.mark.asyncio
async def test_orchestrator_ai_failure_refunds_credits(db_session, setup_base_data, mock_router):
    billing = AsyncMock()
    memory = AsyncMock(spec=MemoryManager)
    memory.get_conversation_history.return_value = []
    queue = AsyncMock()
    
    # Force Mock AI to throw exception explicitly during generation step
    mock_router.route_text_request_with_config.side_effect = Exception("Vertex Timeout")
    
    orchestrator = ChatOrchestrator(db_session, billing, mock_router, memory, queue)
    
    res = await orchestrator.process_message(setup_base_data["user_id"], "crash please", FeatureName.FLASH_TEXT)
    
    assert res.success is False
    assert "Any deducted credits were refunded" in res.text
    # Refund SAGA strictly initiated correctly recovering state!
    billing.refund_credits.assert_called_once()
