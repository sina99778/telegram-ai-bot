import logging
from dataclasses import dataclass
from typing import Optional
from app.services.queue.job_enqueuer import ARQEnqueuer

logger = logging.getLogger(__name__)

@dataclass
class JobResult:
    success: bool
    job_id: Optional[str] = None
    error: Optional[str] = None

class QueueService:
    async def enqueue_summarization(self, conversation_id: int) -> JobResult:
        """Enqueues a summarization job uniquely and returns structured results."""
        job_id = f"sum_chat_{conversation_id}"
        try:
            success = await ARQEnqueuer.enqueue_summarize_chat(conversation_id)
            return JobResult(success=success, job_id=job_id)
        except Exception as e:
            logger.error(f"Failed to enqueue job {job_id}: {e}")
            return JobResult(success=False, error=str(e))
