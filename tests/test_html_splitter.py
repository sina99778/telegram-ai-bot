import pytest
from unittest.mock import AsyncMock, MagicMock
from app.bot.utils.html_splitter import split_html_message
from app.bot.handlers.chat import _deliver_smart_response, send_chunked_message


def test_split_empty_or_short_message():
    assert split_html_message("") == []
    assert split_html_message("Hello world") == ["Hello world"]
    short_html = "<b>Hello</b> <code>world</code>"
    assert split_html_message(short_html) == [short_html]


def test_split_long_plain_text_paragraphs():
    p1 = "Paragraph 1 " * 50  # ~600 chars
    p2 = "Paragraph 2 " * 50
    p3 = "Paragraph 3 " * 50
    text = f"{p1}\n\n{p2}\n\n{p3}"
    chunks = split_html_message(text, max_chunk_size=1000)

    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk) <= 1000
    # Combined content should contain all paragraphs
    full = " ".join(chunks)
    assert "Paragraph 1" in full
    assert "Paragraph 2" in full
    assert "Paragraph 3" in full


def test_split_long_html_balances_tags():
    # Long bold text
    long_inner = "سلام این یک متن طولانی تستی است. " * 50  # ~1700 chars
    text = f"<b>{long_inner}</b>"
    chunks = split_html_message(text, max_chunk_size=600)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 600
        # Every chunk must have properly opened and closed <b> tag
        assert chunk.startswith("<b>")
        assert chunk.endswith("</b>")
        assert chunk.count("<b>") == chunk.count("</b>")


def test_split_code_block_preserves_code_tags():
    code_body = "    x = 1\n    print(x)\n" * 40  # ~900 chars
    text = f'<pre><code class="language-python">\ndef test_func():\n{code_body}</code></pre>'
    chunks = split_html_message(text, max_chunk_size=500)

    assert len(chunks) >= 2
    for idx, chunk in enumerate(chunks):
        assert len(chunk) <= 500
        assert chunk.count("<pre>") == chunk.count("</pre>")
        assert chunk.count("<code") == chunk.count("</code>")


def test_split_nested_html_tags():
    inner = "محتوای تودرتو " * 40
    text = f"<blockquote><b><i>{inner}</i></b></blockquote>"
    chunks = split_html_message(text, max_chunk_size=400)

    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk) <= 400
        # Check all tags are balanced
        assert chunk.count("<blockquote>") == chunk.count("</blockquote>")
        assert chunk.count("<b>") == chunk.count("</b>")
        assert chunk.count("<i>") == chunk.count("</i>")


def test_split_does_not_slice_inside_html_tag_or_entity():
    # Construct a string where a naive cut would slice through <a href="..."> or &amp;
    prefix = "A" * 380
    tag = '<a href="https://example.com/very/long/url/path/test">Click Here</a>'
    text = f"{prefix} {tag} &amp; more text"
    chunks = split_html_message(text, max_chunk_size=420)

    for chunk in chunks:
        # Check no broken tags like '<a' without '>'
        assert "<a href=" not in chunk or ">Click Here</a>" in chunk or chunk.endswith("</a>")
        assert "&amp" not in chunk or "&amp;" in chunk


@pytest.mark.asyncio
async def test_deliver_smart_response_single_chunk():
    trigger_msg = AsyncMock()
    processing_msg = AsyncMock()

    text = "Short answer"
    await _deliver_smart_response(trigger_msg, processing_msg, text)

    processing_msg.edit_text.assert_called_once_with(text, parse_mode="HTML", reply_markup=None)
    trigger_msg.answer.assert_not_called()


@pytest.mark.asyncio
async def test_deliver_smart_response_multi_chunk():
    trigger_msg = AsyncMock()
    processing_msg = AsyncMock()

    p1 = "First part " * 50
    p2 = "Second part " * 50
    text = f"{p1}\n\n{p2}"

    await _deliver_smart_response(trigger_msg, processing_msg, text, chunk_size=500)

    # First chunk edits processing_msg
    assert processing_msg.edit_text.call_count == 1
    # Subsequent chunk(s) sent via trigger_msg.answer
    assert trigger_msg.answer.call_count >= 1
