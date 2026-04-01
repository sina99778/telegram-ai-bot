from __future__ import annotations

from fnmatch import fnmatch

import pytest
import pytest_asyncio

from app.services.security.abuse_guard import AbuseGuardService


class FakePipeline:
    def __init__(self, redis: "FakeRedis"):
        self.redis = redis
        self.ops = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def zremrangebyscore(self, key, min_score, max_score):
        self.ops.append(("zremrangebyscore", key, float(min_score), float(max_score)))

    def zcard(self, key):
        self.ops.append(("zcard", key))

    def zadd(self, key, mapping):
        self.ops.append(("zadd", key, mapping))

    def expire(self, key, seconds):
        self.ops.append(("expire", key, seconds))

    async def execute(self):
        results = []
        for op in self.ops:
            name = op[0]
            if name == "zremrangebyscore":
                results.append(await self.redis.zremrangebyscore(op[1], op[2], op[3]))
            elif name == "zcard":
                results.append(await self.redis.zcard(op[1]))
            elif name == "zadd":
                results.append(await self.redis.zadd(op[1], op[2]))
            elif name == "expire":
                results.append(await self.redis.expire(op[1], op[2]))
        self.ops = []
        return results


class FakeRedis:
    def __init__(self):
        self.zsets = {}
        self.strings = {}
        self.expires = {}

    def pipeline(self, transaction=True):
        return FakePipeline(self)

    async def zremrangebyscore(self, key, min_score, max_score):
        entries = self.zsets.get(key, {})
        to_remove = [member for member, score in entries.items() if min_score <= score <= max_score]
        for member in to_remove:
            entries.pop(member, None)
        if not entries and key in self.zsets:
            self.zsets.pop(key, None)
        return len(to_remove)

    async def zcard(self, key):
        return len(self.zsets.get(key, {}))

    async def zadd(self, key, mapping):
        self.zsets.setdefault(key, {}).update({member: float(score) for member, score in mapping.items()})
        return len(mapping)

    async def expire(self, key, seconds):
        self.expires[key] = seconds
        return True

    async def ttl(self, key):
        return self.expires.get(key, -1) if key in self.strings else -1

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.strings:
            return False
        self.strings[key] = value
        if ex is not None:
            self.expires[key] = ex
        return True

    async def exists(self, key):
        return 1 if key in self.strings else 0

    async def get(self, key):
        return self.strings.get(key)

    async def delete(self, *keys):
        removed = 0
        for key in keys:
            if key in self.strings:
                self.strings.pop(key, None)
                self.expires.pop(key, None)
                removed += 1
        return removed

    async def scan_iter(self, match=None):
        keys = list(self.strings.keys()) + list(self.zsets.keys())
        seen = set()
        for key in keys:
            if key in seen:
                continue
            seen.add(key)
            if match is None or fnmatch(key, match):
                yield key

    async def flushdb(self):
        self.zsets = {}
        self.strings = {}
        self.expires = {}


@pytest_asyncio.fixture(autouse=True)
async def fake_redis():
    redis = FakeRedis()
    await AbuseGuardService.set_client_for_tests(redis)
    yield redis
    await AbuseGuardService.set_client_for_tests(None)


@pytest.mark.asyncio
async def test_private_chat_throttle_blocks_burst():
    user_id = 123
    last_decision = None
    for _ in range(6):
        last_decision = await AbuseGuardService.check_private_chat(user_id=user_id, lang="en")
    assert last_decision is not None
    assert last_decision.allowed is True

    blocked = await AbuseGuardService.check_private_chat(user_id=user_id, lang="en")
    assert blocked.allowed is False


@pytest.mark.asyncio
async def test_repeated_failures_trigger_temp_block():
    user_id = 456
    for _ in range(5):
        await AbuseGuardService.record_failure(subject="image", subject_id=user_id)

    decision = await AbuseGuardService.check_image(user_id=user_id, lang="en")
    assert decision.allowed is False


@pytest.mark.asyncio
async def test_group_request_anomaly_creates_active_flag():
    group_id = 789
    for _ in range(40):
        decision = await AbuseGuardService.check_group_request(group_id=group_id, lang="en")
    assert decision.allowed is True

    anomalies = await AbuseGuardService.list_active_anomalies()
    assert any(item["scope_type"] == "group" and item["scope_id"] == group_id for item in anomalies)
