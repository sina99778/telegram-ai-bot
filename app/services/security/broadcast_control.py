from __future__ import annotations

from redis.asyncio import Redis

from app.core.config import settings


class BroadcastControlService:
    _client: Redis | None = None

    @classmethod
    async def get_client(cls) -> Redis:
        if cls._client is None:
            cls._client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        return cls._client

    @classmethod
    def _active_key(cls, admin_id: int) -> str:
        return f"broadcast:active:{admin_id}"

    @classmethod
    def _stop_key(cls, admin_id: int) -> str:
        return f"broadcast:stop:{admin_id}"

    @classmethod
    async def start(cls, admin_id: int) -> bool:
        client = await cls.get_client()
        started = await client.set(cls._active_key(admin_id), "1", ex=3600, nx=True)
        await client.delete(cls._stop_key(admin_id))
        return bool(started)

    @classmethod
    async def stop(cls, admin_id: int) -> None:
        client = await cls.get_client()
        await client.set(cls._stop_key(admin_id), "1", ex=3600)

    @classmethod
    async def should_stop(cls, admin_id: int) -> bool:
        client = await cls.get_client()
        return bool(await client.exists(cls._stop_key(admin_id)))

    @classmethod
    async def finish(cls, admin_id: int) -> None:
        client = await cls.get_client()
        await client.delete(cls._active_key(admin_id), cls._stop_key(admin_id))
