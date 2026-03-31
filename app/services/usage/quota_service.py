from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import FeatureUsage, User


@dataclass
class QuotaStatus:
    limit: int
    used: int

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    @property
    def exhausted(self) -> bool:
        return self.used >= self.limit


class QuotaService:
    SEARCH_COMMAND = "search_command"
    FREE_IMAGE_GENERATION = "free_image_generation"
    SCOPE_USER = "user"
    SCOPE_GROUP = "group"

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _today() -> date:
        return datetime.now(timezone.utc).date()

    async def _get_usage_row(
        self,
        *,
        scope_type: str,
        scope_id: int,
        feature: str,
        reset_date: date,
        create: bool = False,
    ) -> FeatureUsage | None:
        stmt = select(FeatureUsage).where(
            FeatureUsage.scope_type == scope_type,
            FeatureUsage.scope_id == scope_id,
            FeatureUsage.feature == feature,
            FeatureUsage.reset_date == reset_date,
        )
        usage = await self.session.scalar(stmt)
        if usage or not create:
            return usage

        usage = FeatureUsage(
            scope_type=scope_type,
            scope_id=scope_id,
            feature=feature,
            reset_date=reset_date,
            used_count=0,
        )
        self.session.add(usage)
        await self.session.flush()
        return usage

    @staticmethod
    def search_limit_for_user(user: User) -> int:
        if user.has_active_vip:
            return settings.SEARCH_DAILY_VIP_LIMIT
        if user.lifetime_credits_purchased > 0 or user.is_premium:
            return settings.SEARCH_DAILY_PAID_LIMIT
        return settings.SEARCH_DAILY_FREE_LIMIT

    async def get_search_status_for_user(self, user: User) -> QuotaStatus:
        usage = await self._get_usage_row(
            scope_type=self.SCOPE_USER,
            scope_id=user.id,
            feature=self.SEARCH_COMMAND,
            reset_date=self._today(),
        )
        limit = self.search_limit_for_user(user)
        return QuotaStatus(limit=limit, used=usage.used_count if usage else 0)

    async def get_search_status_for_group(self, group_id: int) -> QuotaStatus:
        usage = await self._get_usage_row(
            scope_type=self.SCOPE_GROUP,
            scope_id=group_id,
            feature=self.SEARCH_COMMAND,
            reset_date=self._today(),
        )
        return QuotaStatus(limit=settings.SEARCH_DAILY_GROUP_LIMIT, used=usage.used_count if usage else 0)

    async def get_free_image_status_for_user(self, user_id: int) -> QuotaStatus:
        usage = await self._get_usage_row(
            scope_type=self.SCOPE_USER,
            scope_id=user_id,
            feature=self.FREE_IMAGE_GENERATION,
            reset_date=self._today(),
        )
        return QuotaStatus(limit=settings.FREE_DAILY_IMAGE_LIMIT, used=usage.used_count if usage else 0)

    async def consume_search_for_user(self, user: User) -> QuotaStatus:
        status = await self.get_search_status_for_user(user)
        if status.exhausted:
            return status
        usage = await self._get_usage_row(
            scope_type=self.SCOPE_USER,
            scope_id=user.id,
            feature=self.SEARCH_COMMAND,
            reset_date=self._today(),
            create=True,
        )
        usage.used_count += 1
        await self.session.commit()
        return QuotaStatus(limit=status.limit, used=usage.used_count)

    async def consume_search_for_group(self, group_id: int) -> QuotaStatus:
        status = await self.get_search_status_for_group(group_id)
        if status.exhausted:
            return status
        usage = await self._get_usage_row(
            scope_type=self.SCOPE_GROUP,
            scope_id=group_id,
            feature=self.SEARCH_COMMAND,
            reset_date=self._today(),
            create=True,
        )
        usage.used_count += 1
        await self.session.commit()
        return QuotaStatus(limit=status.limit, used=usage.used_count)

    async def consume_free_image_for_user(self, user_id: int) -> QuotaStatus:
        status = await self.get_free_image_status_for_user(user_id)
        if status.exhausted:
            return status
        usage = await self._get_usage_row(
            scope_type=self.SCOPE_USER,
            scope_id=user_id,
            feature=self.FREE_IMAGE_GENERATION,
            reset_date=self._today(),
            create=True,
        )
        usage.used_count += 1
        await self.session.commit()
        return QuotaStatus(limit=status.limit, used=usage.used_count)
