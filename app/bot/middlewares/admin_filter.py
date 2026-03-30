from aiogram.filters import Filter
from aiogram.types import Message, CallbackQuery
from app.core.config import settings


class IsAdminFilter(Filter):
    """
    Checks whether the event sender is in settings.ADMIN_IDS.
    Works for both Message and CallbackQuery events so
    the admin_router can protect commands AND inline button presses.
    """

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        admin_ids = settings.admin_ids_list
        if not admin_ids:
            return False

        if isinstance(event, CallbackQuery):
            user_id = event.from_user.id
        else:
            user_id = event.from_user.id

        return user_id in admin_ids
