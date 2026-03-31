from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.core.i18n import t


def nav_buttons(
    lang: str,
    *,
    back: str | None = None,
    home: str | None = None,
    cancel: str | None = None,
    refresh: str | None = None,
) -> list[list[InlineKeyboardButton]]:
    row: list[InlineKeyboardButton] = []
    if back:
        row.append(InlineKeyboardButton(text=t(lang, "buttons.back"), callback_data=back))
    if home:
        row.append(InlineKeyboardButton(text=t(lang, "buttons.home"), callback_data=home))
    if refresh:
        row.append(InlineKeyboardButton(text=t(lang, "buttons.refresh"), callback_data=refresh))
    if cancel:
        row.append(InlineKeyboardButton(text=t(lang, "buttons.cancel"), callback_data=cancel))
    return [row] if row else []


def markup(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[row for row in rows if row])
