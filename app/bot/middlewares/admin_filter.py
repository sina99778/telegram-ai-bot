import os
from aiogram.filters import Filter
from aiogram.types import Message

class IsAdminFilter(Filter):
    """
    MVP Env-Based Admin Filter to swiftly limit specific route access.
    Prepared architecturally to migrate to a DB resolver if user schemas adopt roles.
    """
    async def __call__(self, message: Message) -> bool:
        admin_ids_str = os.environ.get("ADMIN_TELEGRAM_IDS", "")
        if not admin_ids_str:
            return False
            
        admin_ids = [int(x.strip()) for x in admin_ids_str.split(",") if x.strip().isdigit()]
        return message.from_user.id in admin_ids
