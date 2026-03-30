import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from app.services.queue.job_enqueuer import ARQEnqueuer

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    """Outcome of an enqueue attempt."""
    ENQUEUED = "enqueued"
    DUPLICATE = "duplicate"   # Job already pending/running — not an error
    FAILED = "failed"


@dataclass
class JobResult:
    """Structured result returned by every QueueService method.

    Orchestrators should check ``success`` to decide whether to persist
    the ``job_id`` and should never need to inspect ARQ internals.
    """
    success: bool
    status: JobStatus
    job_id: Optional[str] = None
    error: Optional[str] = None


class QueueService:
    """Facade over the ARQ background queue.

    Keeps orchestrators decoupled from ARQ internals; they receive a
    :class:`JobResult` and never import ``arq`` directly.
    """

    async def enqueue_summarization(self, conversation_id: int) -> JobResult:
        """Enqueue a summarization job, deduplicating by conversation ID."""
        job_id = f"sum_chat_{conversation_id}"
        try:
            enqueued = await ARQEnqueuer.enqueue_summarize_chat(conversation_id)
            if enqueued:
                return JobResult(success=True, status=JobStatus.ENQUEUED, job_id=job_id)
            else:
                # Job is already pending or running — this is not an error.
                return JobResult(success=True, status=JobStatus.DUPLICATE, job_id=job_id)
        except Exception as e:
            logger.error(f"Failed to enqueue job {job_id}: {e}")
            return JobResult(success=False, status=JobStatus.FAILED, error=str(e))
