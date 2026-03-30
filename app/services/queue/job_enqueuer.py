import logging
from typing import Optional
from arq import create_pool
from arq.connections import RedisSettings
from arq.interfaces import RedisSettings as ARQRedisSettings
from app.core.config import settings

logger = logging.getLogger(__name__)

class ARQEnqueuer:
    _pool = None

    @classmethod
    async def get_pool(cls):
        """Lazily initialize and return the global Redis ARQ connection pool."""
        if cls._pool is None:
            # Note: Redis url strings must securely map properly
            redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
            cls._pool = await create_pool(redis_settings)
        return cls._pool

    @classmethod
    async def enqueue_summarize_chat(cls, conversation_id: int) -> bool:
        """
        Safely enqueues a Heavy background chat summarization job idempotently.
        """
        try:
            pool = await cls.get_pool()
            # 3. Utilizing explicit strict _job_id prevents duplicate concurrent jobs triggering simultaneously
            job_id = f"sum_chat_{conversation_id}"
            
            job = await pool.enqueue_job("summarize_chat", conversation_id, _job_id=job_id)
            if job:
                logger.info(f"Successfully Queued idempotent summarization job {job.job_id} for Conv: {conversation_id}.")
                return True
            else:
                logger.debug(f"Redundant Enqueue Ignored: Job {job_id} is actively pending or executing flawlessly.")
                return False
        except Exception as e:
            logger.error(f"CRITICAL: Failed to enqueue summarize_chat job dynamically for Conv {conversation_id}: {e}", exc_info=True)
            return False
