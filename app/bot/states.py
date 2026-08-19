from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class ActionStates(StatesGroup):
    waiting_for_image_prompt = State()
    waiting_for_search_query = State()
    waiting_for_image_edit = State()
