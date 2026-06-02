import time

from app.webapp.auth import build_init_data, validate_init_data

TOKEN = "123456:TEST-bot-token-abcdef"
USER = {"id": 555000111, "first_name": "Sina", "username": "sina", "language_code": "fa"}


def test_valid_init_data_passes():
    init = build_init_data(TOKEN, USER)
    parsed = validate_init_data(init, TOKEN)
    assert parsed is not None
    assert parsed.telegram_id == 555000111
    assert parsed.username == "sina"


def test_tampered_hash_rejected():
    init = build_init_data(TOKEN, USER)
    tampered = init.replace("first_name", "first_name").replace(USER["first_name"], "Mallory")
    # the user field changed but the hash wasn't recomputed → must fail
    assert validate_init_data(tampered, TOKEN) is None


def test_wrong_token_rejected():
    init = build_init_data(TOKEN, USER)
    assert validate_init_data(init, "999999:DIFFERENT-token") is None


def test_missing_hash_rejected():
    assert validate_init_data("user=%7B%22id%22%3A1%7D&auth_date=123", TOKEN) is None
    assert validate_init_data("", TOKEN) is None
    assert validate_init_data("x=y", "") is None


def test_stale_init_data_rejected():
    old = int(time.time()) - 100000  # > default 86400s
    init = build_init_data(TOKEN, USER, auth_date=old)
    assert validate_init_data(init, TOKEN) is None
    # but accepted within a large window
    assert validate_init_data(init, TOKEN, max_age_seconds=0) is not None  # 0 disables the check


def test_user_without_id_rejected():
    init = build_init_data(TOKEN, {"first_name": "NoId"})
    assert validate_init_data(init, TOKEN) is None
