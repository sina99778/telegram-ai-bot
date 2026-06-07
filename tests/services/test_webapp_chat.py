"""End-to-end tests for the Mini App chat endpoint.

These prove the contract the frontend depends on: **every** response carries a
non-empty ``reply`` — on auth failure, on an empty message, and on the happy
path. A bare HTTP error with no body (which the SPA renders as "No response")
must never happen.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings
from app.webapp import routes as webapp_routes
from app.webapp.auth import build_init_data

BOT_TOKEN = "424242:TESTtokenTESTtokenTESTtokenTESTtoken"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "BOT_TOKEN", BOT_TOKEN)
    app = FastAPI()
    app.include_router(webapp_routes.webapp_router)
    return TestClient(app)


def _init() -> str:
    return build_init_data(BOT_TOKEN, {"id": 777, "first_name": "T", "language_code": "en"})


def test_chat_without_initdata_returns_reply(client):
    # No X-Telegram-Init-Data header → must NOT be a bodiless 401.
    r = client.post("/webapp/api/chat", data={"message": "hi"})
    assert r.status_code == 200
    j = r.json()
    assert j["success"] is False
    assert j["error"] == "auth"
    assert j["reply"]  # non-empty so the SPA shows a real message


def test_chat_bad_initdata_returns_reply(client):
    r = client.post(
        "/webapp/api/chat",
        headers={"X-Telegram-Init-Data": "user=%7B%22id%22%3A1%7D&hash=deadbeef"},
        data={"message": "hi"},
    )
    j = r.json()
    assert j["error"] == "auth"
    assert j["reply"]


def test_chat_empty_message_returns_reply(client):
    # Valid initData but no text and no file → friendly "type something" reply,
    # and crucially this path never touches the DB/orchestrator.
    r = client.post(
        "/webapp/api/chat",
        headers={"X-Telegram-Init-Data": _init()},
        data={"message": "   "},
    )
    j = r.json()
    assert j["success"] is False
    assert j["error"] == "empty"
    assert j["reply"]


def test_chat_happy_path_returns_ai_reply(client, monkeypatch):
    # ── Fakes so the endpoint runs without a real DB / Redis / AI provider ──
    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class FakeUser:
        id = 1
        telegram_id = 777
        username = None
        first_name = "T"
        language = "en"
        normal_credits = 10
        vip_credits = 0
        has_active_vip = False

    class FakeRepo:
        def __init__(self, _session):
            pass

        async def get_or_create_user(self, *a, **k):
            return FakeUser()

    class FakeResult:
        text = "Hello from the AI 👋"
        success = True
        error_message = None

    class FakeOrchestrator:
        async def process_message(self, **kwargs):
            return FakeResult()

    monkeypatch.setattr(webapp_routes, "AsyncSessionLocal", lambda: FakeSession())
    monkeypatch.setattr(webapp_routes, "ChatRepository", FakeRepo)
    monkeypatch.setattr(webapp_routes, "_build_orchestrator", lambda _s: FakeOrchestrator())

    from app.services.security.abuse_guard import AbuseGuardService, GuardDecision
    from app.services.security.content_filter import ContentFilterService, FilterDecision

    async def _allow_guard(**kwargs):
        return GuardDecision(allowed=True)

    def _allow_content(prompt):
        return FilterDecision(allowed=True)

    monkeypatch.setattr(AbuseGuardService, "check_private_chat", _allow_guard)
    monkeypatch.setattr(ContentFilterService, "check_text_prompt", _allow_content)

    r = client.post(
        "/webapp/api/chat",
        headers={"X-Telegram-Init-Data": _init()},
        data={"message": "hi there"},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["success"] is True
    assert j["reply"] == "Hello from the AI 👋"


def test_index_served_with_no_store(client):
    r = client.get("/webapp")
    assert r.status_code == 200
    assert "no-store" in r.headers.get("cache-control", "")
    assert "<html" in r.text.lower()


def test_looks_like_image_sniffs_bytes_not_content_type():
    assert webapp_routes._looks_like_image(b"\xff\xd8\xff\xe0JFIF") is True   # JPEG
    assert webapp_routes._looks_like_image(b"\x89PNG\r\n\x1a\n....") is True  # PNG
    assert webapp_routes._looks_like_image(b"RIFF\x00\x00\x00\x00WEBP") is True
    assert webapp_routes._looks_like_image(b"#!/bin/bash\nrm -rf /") is False  # spoofed script
    assert webapp_routes._looks_like_image(b"") is False


def test_safe_error_never_leaks_raw_exception_text():
    # Known codes pass through; anything else collapses to a generic code.
    assert webapp_routes._safe_error("insufficient_funds") == "insufficient_funds"
    assert webapp_routes._safe_error("quota_exhausted") == "quota_exhausted"
    assert webapp_routes._safe_error("RuntimeError: AI Generation failed: 500 boom") == "ai_error"
    assert webapp_routes._safe_error(None) is None


def test_chat_blocks_banned_user(client, monkeypatch):
    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class BannedUser:
        id = 1
        telegram_id = 777
        username = None
        first_name = "T"
        language = "en"
        is_banned = True

    class FakeRepo:
        def __init__(self, _s):
            pass

        async def get_or_create_user(self, *a, **k):
            return BannedUser()

    monkeypatch.setattr(webapp_routes, "AsyncSessionLocal", lambda: FakeSession())
    monkeypatch.setattr(webapp_routes, "ChatRepository", FakeRepo)

    r = client.post(
        "/webapp/api/chat",
        headers={"X-Telegram-Init-Data": _init()},
        data={"message": "hi"},
    )
    j = r.json()
    assert j["success"] is False
    assert j["error"] == "banned"
    assert j["reply"]
