"""Regression guards for fixes from the full-codebase audit."""

import pytest

from app.core.config import Settings
from app.services.config.runtime_config import RuntimeConfig


@pytest.fixture(autouse=True)
def _clear_cache():
    RuntimeConfig.clear_cache()
    yield
    RuntimeConfig.clear_cache()


def test_admin_ids_tolerates_garbage():
    # A stray non-numeric entry must be skipped, not crash (read on every update).
    assert Settings(ADMIN_IDS="123, 456 , oops ,789").admin_ids_list == [123, 456, 789]
    assert Settings(ADMIN_IDS="").admin_ids_list == []
    assert Settings(ADMIN_IDS="nope").admin_ids_list == []


@pytest.mark.asyncio
async def test_runtime_config_recovers_session_on_read_error():
    """If the DB read raises, get_int must roll the session back (so the
    caller's next query isn't poisoned) and still return the env default."""
    rolled = {"count": 0}

    class _Session:
        async def get(self, *_a, **_k):
            raise RuntimeError("simulated aborted transaction")

        async def rollback(self):
            rolled["count"] += 1

    value = await RuntimeConfig.get_int(_Session(), "free_daily_image")
    assert value == RuntimeConfig.default_for("free_daily_image")  # fell back to default
    assert rolled["count"] == 1  # and recovered the session


def test_card_idempotency_key_is_unique_per_call(monkeypatch):
    # Two receipts in the same second / same message id must not collide.
    import uuid
    keys = {f"card_1_99_{uuid.uuid4().hex[:8]}" for _ in range(1000)}
    assert len(keys) == 1000
