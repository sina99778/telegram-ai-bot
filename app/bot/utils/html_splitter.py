"""
app/bot/utils/html_splitter.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Intelligent, HTML-aware message chunking for Telegram.

Splits long texts (>4000 chars) into multiple valid Telegram HTML chunks
by respecting natural paragraph/sentence/word boundaries and properly
closing and reopening formatting tags across chunk boundaries.
"""

from __future__ import annotations

import re
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

# Telegram-supported HTML tags
_TAG_RE = re.compile(r"<(/?)(\w[\w-]*)([^>]*)>", re.IGNORECASE)
_ENTITY_RE = re.compile(r"&[a-zA-Z0-9#]+;")

# Sentences and punctuation boundaries
_SENTENCE_END_RE = re.compile(r"([.!?؛؟])\s+")


def _find_safe_cut_point(
    text: str,
    start: int,
    max_len: int,
) -> int:
    """
    Find a natural splitting boundary (paragraph > line > sentence > word > char)
    within text[start : start + max_len] that does not cut through HTML tags or entities.
    Returns relative cut offset from start.
    """
    end = min(start + max_len, len(text))
    window = text[start:end]

    if len(window) <= 0:
        return 0

    # If full window reaches the end of text, no cut search needed
    if end >= len(text):
        return len(window)

    def is_inside_tag_or_entity(offset: int) -> bool:
        """Check if offset is in the middle of <...> or &...;."""
        # Check tag <...>
        last_lt = window.rfind("<", 0, offset)
        last_gt = window.rfind(">", 0, offset)
        if last_lt != -1 and (last_gt == -1 or last_gt < last_lt):
            # Inside tag if closing > is after offset
            next_gt = text.find(">", start + last_lt)
            if next_gt != -1 and next_gt >= start + offset:
                return True

        # Check entity &...;
        last_amp = window.rfind("&", 0, offset)
        last_semi = window.rfind(";", 0, offset)
        if last_amp != -1 and (last_semi == -1 or last_semi < last_amp):
            next_semi = text.find(";", start + last_amp)
            if next_semi != -1 and next_semi >= start + offset and (next_semi - (start + last_amp) < 12):
                return True

        return False

    def adjust_cut(candidate: int) -> int:
        """Ensure candidate doesn't slice inside an HTML tag or entity."""
        if candidate <= 0:
            return 0
        # If inside tag, move candidate before '<'
        last_lt = window.rfind("<", 0, candidate)
        last_gt = window.rfind(">", 0, candidate)
        if last_lt != -1 and (last_gt == -1 or last_gt < last_lt):
            candidate = last_lt

        # If inside entity, move candidate before '&'
        last_amp = window.rfind("&", 0, candidate)
        last_semi = window.rfind(";", 0, candidate)
        if last_amp != -1 and (last_semi == -1 or last_semi < last_amp):
            candidate = last_amp

        return max(0, candidate)

    # 1. Paragraph boundary: \n\n
    # Prefer paragraph splits in the second half of the window
    p_idx = window.rfind("\n\n")
    if p_idx != -1 and p_idx >= len(window) // 3:
        cut = adjust_cut(p_idx + 2)
        if cut > 0:
            return cut

    # 2. Line break: \n
    n_idx = window.rfind("\n")
    if n_idx != -1 and n_idx >= len(window) // 4:
        cut = adjust_cut(n_idx + 1)
        if cut > 0:
            return cut

    # 3. Sentence end: . / ! / ? / ؛ / ؟ followed by space or newline
    sentence_matches = list(_SENTENCE_END_RE.finditer(window))
    for sm in reversed(sentence_matches):
        if sm.end() >= len(window) // 4:
            cut = adjust_cut(sm.end())
            if cut > 0:
                return cut

    # 4. Word boundary: whitespace
    sp_idx = window.rfind(" ")
    if sp_idx != -1 and sp_idx >= len(window) // 4:
        cut = adjust_cut(sp_idx + 1)
        if cut > 0:
            return cut

    # 5. Fallback: hard cut adjusted for tags
    fallback = adjust_cut(len(window))
    if fallback > 0:
        return fallback

    # 6. Extreme fallback: if tag itself was longer than window, advance past the tag
    next_gt = text.find(">", start)
    if next_gt != -1:
        return (next_gt + 1) - start

    return len(window)


def split_html_message(text: str, max_chunk_size: int = 4000) -> list[str]:
    """
    Split an HTML text into chunks that are each <= max_chunk_size characters,
    ensuring that opening tags are cleanly closed in each chunk and reopened in
    the next chunk.
    """
    if not text:
        return []

    text = text.strip()
    if len(text) <= max_chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    total_len = len(text)

    # Stack of (tag_name, full_opening_tag) e.g. ("pre", "<pre>"), ("code", '<code class="python">')
    open_tag_stack: list[tuple[str, str]] = []

    while start < total_len:
        prefix = "".join(full_tag for _, full_tag in open_tag_stack)
        suffix_est_len = sum(len(tag_name) + 3 for tag_name, _ in open_tag_stack)

        # Dynamic budget based on current prefix and estimated suffix
        available_budget = max_chunk_size - len(prefix) - suffix_est_len - 10
        if available_budget <= 20:
            available_budget = max(10, max_chunk_size // 2)

        # Find safe cut point
        cut_len = _find_safe_cut_point(text, start, available_budget)
        if cut_len <= 0:
            cut_len = min(available_budget, total_len - start)
            if cut_len <= 0:
                break

        def _compute_chunk(c_len: int) -> tuple[str, list[tuple[str, str]], int]:
            candidate_slice = text[start : start + c_len]
            stack_copy = list(open_tag_stack)
            for match in _TAG_RE.finditer(candidate_slice):
                is_closing = bool(match.group(1))
                tag_name = match.group(2).lower()
                full_tag = match.group(0)

                if full_tag.endswith("/>"):
                    continue

                if is_closing:
                    for idx in range(len(stack_copy) - 1, -1, -1):
                        if stack_copy[idx][0] == tag_name:
                            stack_copy.pop(idx)
                            break
                else:
                    stack_copy.append((tag_name, full_tag))

            suf = "".join(f"</{tag_name}>" for tag_name, _ in reversed(stack_copy))
            res = f"{prefix}{candidate_slice}{suf}".strip()
            return res, stack_copy, c_len

        chunk_str, new_stack, actual_cut = _compute_chunk(cut_len)

        # If chunk_str still exceeds max_chunk_size due to long tags, shrink cut_len safely
        while len(chunk_str) > max_chunk_size and actual_cut > 10:
            reduced = max(5, int(actual_cut * 0.8))
            new_cut = _find_safe_cut_point(text, start, reduced)
            if new_cut >= actual_cut or new_cut <= 0:
                actual_cut = max(5, actual_cut - 10)
            else:
                actual_cut = new_cut
            chunk_str, new_stack, actual_cut = _compute_chunk(actual_cut)

        open_tag_stack = new_stack
        if chunk_str:
            chunks.append(chunk_str)

        start += actual_cut

        # If start is whitespace, we can advance past it if outside pre/code
        is_in_code = any(t in ("pre", "code") for t, _ in open_tag_stack)
        if not is_in_code and start < total_len and text[start] in ("\n", " "):
            # Advance past single leading whitespace at boundary
            if text[start] == "\n":
                start += 1
            elif text[start] == " ":
                start += 1

    return chunks if chunks else [text]
