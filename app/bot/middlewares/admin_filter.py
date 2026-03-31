from aiogram.filters import Filter
from aiogram.types import Message, CallbackQuery
from app.core.access import is_configured_admin


class IsAdminFilter(Filter):
    """
    Checks whether the event sender is in settings.ADMIN_IDS.
    Works for both Message and CallbackQuery events so
    the admin_router can protect commands AND inline button presses.
    """

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        if isinstance(event, CallbackQuery):
            user_id = event.from_user.id
        else:
            user_id = event.from_user.id

        return is_configured_admin(user_id)
