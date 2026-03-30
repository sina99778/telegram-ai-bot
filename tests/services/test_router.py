from app.services.ai.router import sanitize_telegram_html


def test_sanitize_telegram_html_converts_balanced_markdown():
    text = "Use **bold** and `code` safely."

    assert sanitize_telegram_html(text) == "Use <b>bold</b> and <code>code</code> safely."


def test_sanitize_telegram_html_leaves_unbalanced_markdown_unchanged():
    text = "This **stays open and this `too."

    assert sanitize_telegram_html(text) == text
