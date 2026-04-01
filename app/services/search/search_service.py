from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import FeatureName
from app.core.i18n import t
from app.db.models import User
from app.services.ai.router import ModelRouter, sanitize_telegram_html
from app.services.usage.quota_service import QuotaService

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    success: bool
    text: str
    quota_limit: int
    quota_used: int
    model_name: str | None = None
    error_code: str | None = None


class SearchService:
    def __init__(self, session: AsyncSession, router: ModelRouter, quota_service: QuotaService):
        self.session = session
        self.router = router
        self.quota_service = quota_service

    async def _execute(self, *, prompt: str, lang: str) -> tuple[str, str]:
        config = await self.router._get_feature_config(FeatureName.FLASH_TEXT)
        response = await self.router.route_text_request_with_config(
            config=config,
            prompt=prompt,
            history=[],
            persona="search_assistant",
            language=lang,
            enable_search=True,
        )
        text = sanitize_telegram_html(response.text).strip()
        if not text:
            text = t(lang, "search.no_results")
        return text, response.model_name

    async def search_for_user(self, *, user: User, query: str) -> SearchResult:
        lang = user.language or "fa"
        status = await self.quota_service.get_search_status_for_user(user)
        logger.info("Search request user_id=%s scope=user used=%s limit=%s", user.id, status.used, status.limit)
        if status.exhausted:
            logger.warning("Search quota exhausted user_id=%s limit=%s", user.id, status.limit)
            return SearchResult(
                success=False,
                text=t(lang, "search.quota_exhausted_user", limit=status.limit),
                quota_limit=status.limit,
                quota_used=status.used,
                error_code="quota_exhausted",
            )

        try:
            text, model_name = await self._execute(prompt=query, lang=lang)
        except Exception as exc:
            logger.error("Private search failed for user_id=%s: %s", user.id, exc, exc_info=True)
            return SearchResult(
                success=False,
                text=t(lang, "search.temporary_failure"),
                quota_limit=status.limit,
                quota_used=status.used,
                error_code="search_failed",
            )

        updated_status = await self.quota_service.consume_search_for_user(user)
        logger.info("Search success user_id=%s quota_used=%s/%s", user.id, updated_status.used, updated_status.limit)
        return SearchResult(
            success=True,
            text=text,
            quota_limit=updated_status.limit,
            quota_used=updated_status.used,
            model_name=model_name,
        )

    async def search_for_group(self, *, user: User, group_id: int, query: str) -> SearchResult:
        lang = user.language or "fa"
        status = await self.quota_service.get_search_status_for_group(group_id)
        logger.info("Search request user_id=%s scope=group group_id=%s used=%s limit=%s", user.id, group_id, status.used, status.limit)
        if status.exhausted:
            logger.warning("Group search quota exhausted group_id=%s limit=%s", group_id, status.limit)
            return SearchResult(
                success=False,
                text=t(lang, "search.quota_exhausted_group", limit=status.limit),
                quota_limit=status.limit,
                quota_used=status.used,
                error_code="quota_exhausted",
            )

        try:
            text, model_name = await self._execute(prompt=query, lang=lang)
        except Exception as exc:
            logger.error("Group search failed for group_id=%s: %s", group_id, exc, exc_info=True)
            return SearchResult(
                success=False,
                text=t(lang, "search.temporary_failure"),
                quota_limit=status.limit,
                quota_used=status.used,
                error_code="search_failed",
            )

        updated_status = await self.quota_service.consume_search_for_group(group_id)
        logger.info("Group search success group_id=%s quota_used=%s/%s", group_id, updated_status.used, updated_status.limit)
        return SearchResult(
            success=True,
            text=text,
            quota_limit=updated_status.limit,
            quota_used=updated_status.used,
            model_name=model_name,
        )
