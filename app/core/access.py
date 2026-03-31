from __future__ import annotations

from app.core.config import settings


def is_configured_admin(user_id: int | None) -> bool:
    if user_id is None:
        return False
    return user_id in settings.admin_ids_list
