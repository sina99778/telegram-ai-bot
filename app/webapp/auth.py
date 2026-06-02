"""
app/webapp/auth.py
~~~~~~~~~~~~~~~~~~~
Validation of Telegram Mini App ``initData``.

Every Mini App request carries the ``initData`` string Telegram signed with
the bot token. We re-derive the HMAC exactly as Telegram specifies and compare
it in constant time — this is the ONLY thing that proves the caller is a real
Telegram user in our bot, so the rest of the web API trusts it.

Spec: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
  secret_key   = HMAC_SHA256(key="WebAppData", msg=bot_token)
  check_string = "\n".join(sorted "key=value" excluding hash)
  valid        = hex(HMAC_SHA256(key=secret_key, msg=check_string)) == hash
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

logger = logging.getLogger(__name__)


@dataclass
class WebAppUser:
    telegram_id: int
    first_name: str | None
    username: str | None
    language_code: str | None
    auth_date: int


def validate_init_data(init_data: str, bot_token: str, *, max_age_seconds: int = 86400) -> WebAppUser | None:
    """Return the verified :class:`WebAppUser` or ``None`` if anything is off
    (bad signature, missing/garbled fields, stale auth_date)."""
    if not init_data or not bot_token:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))
    except Exception:
        return None

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None

    check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    computed = hmac.new(secret_key, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, received_hash):
        return None

    # Freshness — reject replays of old initData.
    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError:
        auth_date = 0
    if max_age_seconds and auth_date and (time.time() - auth_date) > max_age_seconds:
        logger.info("Rejected stale Mini App initData auth_date=%s", auth_date)
        return None

    # Parse the user object.
    try:
        user = json.loads(pairs.get("user", "{}"))
    except Exception:
        user = {}
    tg_id = user.get("id")
    if not isinstance(tg_id, int):
        return None

    return WebAppUser(
        telegram_id=tg_id,
        first_name=user.get("first_name"),
        username=user.get("username"),
        language_code=user.get("language_code"),
        auth_date=auth_date,
    )


def build_init_data(bot_token: str, user: dict, *, auth_date: int | None = None, extra: dict | None = None) -> str:
    """Helper used by tests to construct a correctly-signed initData string."""
    from urllib.parse import urlencode

    pairs: dict[str, str] = {}
    if extra:
        pairs.update({k: str(v) for k, v in extra.items()})
    pairs["auth_date"] = str(auth_date if auth_date is not None else int(time.time()))
    pairs["user"] = json.dumps(user, separators=(",", ":"))
    check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret_key, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    return urlencode(pairs)
