import logging
from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import text
from app.core.config import settings
from app.services.ai.antigravity import AntigravityProvider
from app.workers.tasks_ai import summarize_chat

# 7. Scalable registry logic ready for additional domain workers effortlessly:
# from app.workers.tasks_billing import retry_payments, refund_processor
# from app.workers.tasks_images import prune_image_bucket

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

async def startup(ctx: dict):
    """Initializes scalable DB connection pools, explicitly verifies startup readiness, and securely injects Provider registries."""
    logging.info("Worker starting... Initializing isolated startup readiness infrastructure.")
    
    # 10. Service readiness protection handling DB Connections securely
    engine = create_async_engine(settings.database_url, pool_size=10, max_overflow=20)
    
    # Test DB Connection before marking ARQ ready safely
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as connection_err:
        logging.critical(f"Database readiness probe explicitly failed strictly: {connection_err}")
        raise
        
    ctx['engine'] = engine  # 6. Correctly retain explicit engine allocation bound
    ctx['session_maker'] = async_sessionmaker(engine, expire_on_commit=False)
    
    # 2. Explict Factory Injection to avoid instantiating external providers repeatedly inside job logic scopes
    ctx['providers'] = {
        'antigravity': AntigravityProvider()
    }
    
    logging.info("Worker ready. Redis + Postgres Connections definitively verified.")

async def shutdown(ctx: dict):
    if engine := ctx.get('engine'):
        await engine.dispose()
    logging.info("Worker forcefully shut down perfectly gracefully. Postgres explicit Engine pooled disconnected.")

class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    functions = [summarize_chat]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 20
