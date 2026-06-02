"""Telegram callback alerts (callback.answer(show_alert=True)) render as PLAIN
text — HTML tags show up literally (e.g. a raw <code>…</code>). Any i18n key
shown in an alert must therefore contain no markup.
"""

import pytest

from app.core.i18n import t

# Keys that are surfaced via callback.answer(..., show_alert=True).
ALERT_KEYS = [
    "errors.access_denied",
    "admin.config.unknown_key",
    "admin.config.rate_fetched",
    "admin.config.rate_failed",
    "admin.cardpay.approved",
    "admin.cardpay.rejected",
    "admin.cardpay.already",
    "admin.cardpay.not_found",
]


@pytest.mark.parametrize("lang", ["en", "fa"])
@pytest.mark.parametrize("key", ALERT_KEYS)
def test_alert_strings_have_no_html(lang, key):
    raw = t(lang, key)  # template form, before .format
    assert "<" not in raw and ">" not in raw, f"{key} ({lang}) contains HTML, breaks alerts: {raw!r}"
