from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import FeatureName, LedgerEntryType, PromoCodeKind, WalletType
from app.db.models import CreditLedger, FeatureConfig, FeatureUsage, PaymentTransaction, PromoCode, User, UserPromo
from app.services.billing.billing_service import BillingService
from app.services.security.abuse_guard import AbuseGuardService

logger = logging.getLogger(__name__)


@dataclass
class PaginatedUsers:
    users: list[User]
    page: int
    page_size: int
    total_count: int

    @property
    def total_pages(self) -> int:
        return max(1, math.ceil(self.total_count / self.page_size))


class AdminService:
    def __init__(self, session: AsyncSession, billing: BillingService):
        self.session = session
        self.billing = billing

    async def add_credits_to_user(
        self,
        admin_telegram_id: int,
        target_telegram_id: int,
        amount: int,
        wallet_type: WalletType = WalletType.NORMAL,
    ) -> int:
        if amount <= 0:
            raise ValueError("Credit amount must be positive.")

        user = await self.get_user_details(target_telegram_id)
        logger.info(
            "Admin credit grant requested admin_telegram_id=%s target_telegram_id=%s wallet=%s amount=%s",
            admin_telegram_id,
            target_telegram_id,
            wallet_type.value,
            amount,
        )
        return await self.billing.add_credits(
            user_id=user.id,
            amount=amount,
            entry_type=LedgerEntryType.ADMIN_ADJUSTMENT,
            reference_type="admin_grant",
            reference_id=f"admin_{admin_telegram_id}_{wallet_type.value.lower()}_{uuid.uuid4().hex[:8]}",
            description=f"Admin {admin_telegram_id} granted {amount} {wallet_type.value.lower()} credits",
            wallet_type=wallet_type,
        )

    async def grant_vip_to_user(self, admin_telegram_id: int, target_telegram_id: int, days: int) -> datetime:
        user = await self.get_user_details(target_telegram_id)
        logger.info(
            "Admin VIP grant requested admin_telegram_id=%s target_telegram_id=%s days=%s",
            admin_telegram_id,
            target_telegram_id,
            days,
        )
        return await self.billing.grant_vip_access(
            user_id=user.id,
            days=days,
            reference_type="admin_vip_grant",
            reference_id=f"vip_{admin_telegram_id}_{uuid.uuid4().hex[:8]}",
            description=f"Admin {admin_telegram_id} granted VIP access for {days} days",
        )

    async def set_user_ban_status(self, target_telegram_id: int, banned: bool) -> User:
        user = await self.get_user_details(target_telegram_id)
        user.is_banned = banned
        await self.session.commit()
        await self.session.refresh(user)
        logger.info("Admin ban status changed target_telegram_id=%s banned=%s", target_telegram_id, banned)
        return user

    async def update_feature_price(self, feature_name: FeatureName, new_cost: int) -> bool:
        if new_cost <= 0:
            raise ValueError("Feature cost must be positive.")

        feature = await self.session.scalar(select(FeatureConfig).where(FeatureConfig.name == feature_name))
        if not feature:
            raise ValueError("Feature not located.")

        feature.credit_cost = new_cost
        await self.session.commit()
        await self.session.refresh(feature)
        return True

    async def list_users(self, page: int = 1, page_size: int = 8, search: str | None = None) -> PaginatedUsers:
        page = max(1, page)
        page_size = min(max(1, page_size), 25)

        stmt = select(User)
        count_stmt = select(func.count(User.id))

        if search:
            search = search.strip()
            if search:
                filters = [
                    User.username.ilike(f"%{search}%"),
                    User.first_name.ilike(f"%{search}%"),
                ]
                if search.isdigit():
                    filters.append(User.telegram_id == int(search))
                clause = or_(*filters)
                stmt = stmt.where(clause)
                count_stmt = count_stmt.where(clause)

        total_count = await self.session.scalar(count_stmt) or 0
        result = await self.session.scalars(
            stmt.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
        return PaginatedUsers(
            users=list(result.all()),
            page=page,
            page_size=page_size,
            total_count=total_count,
        )

    async def get_system_stats(self) -> dict[str, Any]:
        total_users = await self.session.scalar(select(func.count(User.id))) or 0
        total_active = await self.session.scalar(select(func.count(User.id)).where(User.lifetime_credits_used > 0)) or 0
        total_vip = await self.session.scalar(select(func.count(User.id)).where(User.is_vip.is_(True))) or 0
        total_banned = await self.session.scalar(select(func.count(User.id)).where(User.is_banned.is_(True))) or 0

        total_normal = await self.session.scalar(select(func.sum(User.normal_credits))) or 0
        total_vip_credits = await self.session.scalar(select(func.sum(User.vip_credits))) or 0
        total_lifetime_used = await self.session.scalar(select(func.sum(User.lifetime_credits_used))) or 0
        total_lifetime_purchased = await self.session.scalar(select(func.sum(User.lifetime_credits_purchased))) or 0

        total_payments_done = await self.session.scalar(
            select(func.count(PaymentTransaction.id)).where(PaymentTransaction.status == "COMPLETED")
        ) or 0
        total_payments_fail = await self.session.scalar(
            select(func.count(PaymentTransaction.id)).where(PaymentTransaction.status == "FAILED")
        ) or 0

        return {
            "total_users": total_users,
            "total_active_users": total_active,
            "total_vip_users": total_vip,
            "total_banned_users": total_banned,
            "total_normal_credits": total_normal,
            "total_vip_credits": total_vip_credits,
            "total_credits_circulation": total_normal + total_vip_credits,
            "total_lifetime_used": total_lifetime_used,
            "total_lifetime_purchased": total_lifetime_purchased,
            "total_payments_completed": total_payments_done,
            "total_payments_failed": total_payments_fail,
        }

    async def get_user_details(self, telegram_id: int) -> User:
        user = await self.session.scalar(select(User).where(User.telegram_id == telegram_id))
        if not user:
            raise ValueError("User not found.")
        return user

    async def get_user_ledger(self, telegram_id: int, limit: int = 10) -> list[CreditLedger]:
        user = await self.get_user_details(telegram_id)
        limit = min(limit, 50)
        result = await self.session.scalars(
            select(CreditLedger)
            .where(CreditLedger.user_id == user.id)
            .order_by(CreditLedger.id.desc())
            .limit(limit)
        )
        return result.all()

    async def create_promo_code(
        self,
        admin_telegram_id: int,
        *,
        kind: PromoCodeKind,
        code: str,
        normal_credits: int = 0,
        vip_credits: int = 0,
        vip_days: int = 0,
        discount_percent: int = 0,
        max_uses: int = 1,
        max_uses_per_user: int = 1,
        expires_at: datetime | None = None,
    ) -> PromoCode:
        promo = PromoCode(
            code=code.upper(),
            kind=kind,
            normal_credits=max(0, normal_credits),
            vip_credits=max(0, vip_credits),
            vip_days=max(0, vip_days),
            discount_percent=max(0, discount_percent),
            max_uses=max(1, max_uses),
            max_uses_per_user=max(1, max_uses_per_user),
            created_by_admin_id=admin_telegram_id,
            expires_at=expires_at,
            is_active=True,
        )
        self.session.add(promo)
        await self.session.commit()
        await self.session.refresh(promo)
        logger.info(
            "Admin promo created admin_telegram_id=%s code=%s kind=%s max_uses=%s",
            admin_telegram_id,
            promo.code,
            promo.kind.value,
            promo.max_uses,
        )
        return promo

    async def list_promo_codes(self, active_only: bool = True, limit: int = 20) -> list[PromoCode]:
        stmt = select(PromoCode).order_by(PromoCode.created_at.desc()).limit(min(limit, 50))
        if active_only:
            stmt = stmt.where(PromoCode.is_active.is_(True))
        result = await self.session.scalars(stmt)
        return result.all()

    async def disable_promo_code(self, promo_id: int) -> PromoCode:
        promo = await self.session.get(PromoCode, promo_id)
        if not promo:
            raise ValueError("Promo code not found.")
        promo.is_active = False
        await self.session.commit()
        await self.session.refresh(promo)
        logger.info("Admin promo disabled promo_id=%s code=%s", promo_id, promo.code)
        return promo

    async def get_promo_usage(self, promo_id: int) -> dict[str, Any]:
        promo = await self.session.get(PromoCode, promo_id)
        if not promo:
            raise ValueError("Promo code not found.")

        result = await self.session.scalars(
            select(UserPromo).where(UserPromo.promo_id == promo_id).order_by(UserPromo.redeemed_at.desc())
        )
        redemptions = result.all()
        return {
            "promo": promo,
            "used_count": promo.used_count,
            "redemptions": redemptions,
        }

    async def redeem_promo_code(self, telegram_id: int, code: str) -> PromoCode:
        user = await self.get_user_details(telegram_id)
        promo = await self.session.scalar(select(PromoCode).where(PromoCode.code == code.upper()))
        if not promo or not promo.is_active:
            raise ValueError("Promo code is invalid or inactive.")

        now = datetime.now(timezone.utc)
        if promo.expires_at and promo.expires_at < now:
            raise ValueError("Promo code has expired.")
        if promo.used_count >= promo.max_uses:
            raise ValueError("Promo code usage limit has been reached.")

        usage = await self.session.scalar(
            select(UserPromo).where(UserPromo.user_id == user.id, UserPromo.promo_id == promo.id)
        )
        if usage and usage.used_count >= promo.max_uses_per_user:
            raise ValueError("You have already used this promo code the maximum number of times.")

        if promo.normal_credits:
            await self.billing.add_credits(
                user_id=user.id,
                amount=promo.normal_credits,
                entry_type=LedgerEntryType.BONUS,
                reference_type="promo_normal",
                reference_id=f"promo_normal_{promo.id}_{user.id}_{promo.used_count + 1}",
                description=f"Redeemed promo code {promo.code}",
                wallet_type=WalletType.NORMAL,
            )
        if promo.vip_credits:
            await self.billing.add_credits(
                user_id=user.id,
                amount=promo.vip_credits,
                entry_type=LedgerEntryType.BONUS,
                reference_type="promo_vip",
                reference_id=f"promo_vip_{promo.id}_{user.id}_{promo.used_count + 1}",
                description=f"Redeemed promo code {promo.code}",
                wallet_type=WalletType.VIP,
            )
        if promo.vip_days:
            await self.billing.grant_vip_access(
                user_id=user.id,
                days=promo.vip_days,
                reference_type="promo_vip_days",
                reference_id=f"promo_vip_days_{promo.id}_{user.id}_{promo.used_count + 1}",
                description=f"Redeemed VIP access promo code {promo.code}",
            )

        promo.used_count += 1
        if usage:
            usage.used_count += 1
            usage.redeemed_at = now
        else:
            self.session.add(UserPromo(user_id=user.id, promo_id=promo.id, used_count=1, redeemed_at=now))

        await self.session.commit()
        await self.session.refresh(promo)
        return promo

    async def get_abuse_overview(self) -> dict[str, Any]:
        ledger_counts = await self.session.execute(
            select(CreditLedger.user_id, func.count(CreditLedger.id))
            .where(CreditLedger.reference_type.in_(["chat_message", "image_generation"]))
            .group_by(CreditLedger.user_id)
        )
        usage_counts = await self.session.execute(
            select(FeatureUsage.scope_id, FeatureUsage.feature, func.sum(FeatureUsage.used_count))
            .where(FeatureUsage.scope_type == "user")
            .group_by(FeatureUsage.scope_id, FeatureUsage.feature)
        )

        user_totals: dict[int, int] = {}
        for user_id, count in ledger_counts.all():
            user_totals[user_id] = user_totals.get(user_id, 0) + int(count or 0)
        for scope_id, _feature, used in usage_counts.all():
            user_totals[int(scope_id)] = user_totals.get(int(scope_id), 0) + int(used or 0)

        top_user_ids = [user_id for user_id, _count in sorted(user_totals.items(), key=lambda item: item[1], reverse=True)[:5]]
        users_map = {}
        if top_user_ids:
            users = (
                await self.session.scalars(select(User).where(User.id.in_(top_user_ids)))
            ).all()
            users_map = {user.id: user for user in users}
        top_users = [
            {
                "telegram_id": users_map[user_id].telegram_id,
                "name": users_map[user_id].username or users_map[user_id].first_name or "unknown",
                "count": count,
            }
            for user_id, count in sorted(user_totals.items(), key=lambda item: item[1], reverse=True)[:5]
            if user_id in users_map
        ]

        top_groups_result = await self.session.execute(
            select(FeatureUsage.scope_id, func.sum(FeatureUsage.used_count).label("used"))
            .where(
                FeatureUsage.scope_type == "group",
                FeatureUsage.feature == "search_command",
            )
            .group_by(FeatureUsage.scope_id)
            .order_by(desc("used"))
            .limit(5)
        )
        top_groups = [{"group_id": int(group_id), "count": int(used or 0)} for group_id, used in top_groups_result.all()]

        free_image_result = await self.session.execute(
            select(FeatureUsage.scope_id, func.sum(FeatureUsage.used_count))
            .where(
                FeatureUsage.scope_type == "user",
                FeatureUsage.feature == "free_image_generation",
            )
            .group_by(FeatureUsage.scope_id)
        )
        premium_image_result = await self.session.execute(
            select(CreditLedger.user_id, func.count(CreditLedger.id))
            .where(CreditLedger.reference_type == "image_generation")
            .group_by(CreditLedger.user_id)
        )
        image_totals: dict[int, int] = {}
        for scope_id, used in free_image_result.all():
            image_totals[int(scope_id)] = image_totals.get(int(scope_id), 0) + int(used or 0)
        for user_id, count in premium_image_result.all():
            image_totals[int(user_id)] = image_totals.get(int(user_id), 0) + int(count or 0)

        top_image_user_ids = [user_id for user_id, _count in sorted(image_totals.items(), key=lambda item: item[1], reverse=True)[:5]]
        image_users_map = {}
        if top_image_user_ids:
            image_users = (
                await self.session.scalars(select(User).where(User.id.in_(top_image_user_ids)))
            ).all()
            image_users_map = {user.id: user for user in image_users}
        top_images = [
            {
                "telegram_id": image_users_map[user_id].telegram_id,
                "name": image_users_map[user_id].username or image_users_map[user_id].first_name or "unknown",
                "count": count,
            }
            for user_id, count in sorted(image_totals.items(), key=lambda item: item[1], reverse=True)[:5]
            if user_id in image_users_map
        ]

        active_anomalies = await AbuseGuardService.list_active_anomalies(limit=15)
        feature_anomaly_counts: dict[str, int] = {}
        contained_users: list[dict[str, Any]] = []
        contained_groups: list[dict[str, Any]] = []
        for item in active_anomalies:
            feature_anomaly_counts[item["feature"]] = feature_anomaly_counts.get(item["feature"], 0) + 1
            if item["scope_type"] == "user":
                contained_users.append(item)
            elif item["scope_type"] == "group":
                contained_groups.append(item)

        return {
            "top_users": top_users,
            "top_groups": top_groups,
            "top_images": top_images,
            "temp_blocks": await AbuseGuardService.list_temp_blocks(limit=10),
            "recent_failures": await AbuseGuardService.list_recent_failures(limit=10),
            "active_anomalies": active_anomalies,
            "contained_users": contained_users[:10],
            "contained_groups": contained_groups[:10],
            "recent_spikes": active_anomalies[:10],
            "feature_anomaly_counts": feature_anomaly_counts,
        }
