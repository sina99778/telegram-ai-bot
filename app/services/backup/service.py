from __future__ import annotations

import asyncio
import gzip
import logging
import os
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot
from aiogram.types import FSInputFile
from redis.asyncio import Redis

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class BackupResult:
    path: Path
    size_bytes: int
    created_at: datetime


class DailyBackupService:
    _client: Redis | None = None

    @classmethod
    async def get_client(cls) -> Redis:
        if cls._client is None:
            cls._client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        return cls._client

    @classmethod
    async def set_client_for_tests(cls, client: Redis | Any) -> None:
        cls._client = client

    @classmethod
    def resolve_recipient_id(cls) -> int | None:
        if settings.BACKUP_RECIPIENT_TELEGRAM_ID > 0:
            return settings.BACKUP_RECIPIENT_TELEGRAM_ID
        if settings.admin_ids_list:
            return settings.admin_ids_list[0]
        return None

    @classmethod
    def get_timezone(cls) -> ZoneInfo:
        try:
            return ZoneInfo(settings.BACKUP_TIMEZONE)
        except ZoneInfoNotFoundError:
            logger.warning(
                "Backup timezone is invalid; falling back to UTC backup_timezone=%s",
                settings.BACKUP_TIMEZONE,
            )
            return ZoneInfo("UTC")

    @classmethod
    def get_scheduled_time(cls) -> time:
        raw = settings.BACKUP_SCHEDULE_TIME.strip()
        try:
            hour_str, minute_str = raw.split(":", 1)
            hour = int(hour_str)
            minute = int(minute_str)
            return time(hour=hour, minute=minute)
        except Exception:
            logger.warning("Backup schedule time is invalid; falling back to 03:00 backup_time=%s", raw)
            return time(hour=3, minute=0)

    @classmethod
    def _marker_key(cls, backup_date: str) -> str:
        return f"ops:backup:daily:{backup_date}"

    @classmethod
    def _lock_key(cls) -> str:
        return "ops:backup:lock"

    @classmethod
    async def run_scheduler(cls, bot: Bot) -> None:
        logger.info(
            "Daily backup scheduler started enabled=%s time=%s timezone=%s",
            settings.BACKUP_ENABLED,
            settings.BACKUP_SCHEDULE_TIME,
            settings.BACKUP_TIMEZONE,
        )
        while True:
            try:
                await cls.maybe_run_scheduled_backup(bot)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Daily backup scheduler loop failed")
            await asyncio.sleep(max(settings.BACKUP_CHECK_INTERVAL_SECONDS, 10))

    @classmethod
    async def maybe_run_scheduled_backup(cls, bot: Bot) -> bool:
        if not settings.BACKUP_ENABLED:
            return False

        recipient_id = cls.resolve_recipient_id()
        if recipient_id is None:
            logger.warning("Daily backup is enabled but no backup recipient is configured")
            return False

        tz = cls.get_timezone()
        now_local = datetime.now(tz)
        scheduled = cls.get_scheduled_time()
        if now_local.time().replace(second=0, microsecond=0) < scheduled:
            return False

        backup_date = now_local.date().isoformat()
        client = await cls.get_client()
        marker_key = cls._marker_key(backup_date)
        if await client.exists(marker_key):
            return False

        lock_token = uuid4().hex
        if not await client.set(cls._lock_key(), lock_token, ex=settings.BACKUP_LOCK_SECONDS, nx=True):
            return False

        try:
            if await client.exists(marker_key):
                return False
            result = await cls.create_and_send_backup(bot=bot, recipient_id=recipient_id, now_local=now_local)
            await client.set(marker_key, result.path.name, ex=int(timedelta(days=3).total_seconds()))
            return True
        finally:
            try:
                current_token = await client.get(cls._lock_key())
                if current_token == lock_token:
                    await client.delete(cls._lock_key())
            except Exception:
                logger.warning("Could not release backup scheduler lock", exc_info=True)

    @classmethod
    async def create_and_send_backup(
        cls,
        *,
        bot: Bot,
        recipient_id: int,
        now_local: datetime | None = None,
    ) -> BackupResult:
        created_at = now_local or datetime.now(cls.get_timezone())
        logger.info(
            "Starting daily PostgreSQL backup recipient_id=%s scheduled_time=%s",
            recipient_id,
            created_at.isoformat(),
        )
        result = await cls.create_database_backup(created_at=created_at)
        try:
            await cls.send_backup(bot=bot, recipient_id=recipient_id, result=result)
        except Exception:
            logger.exception(
                "Daily backup delivery failed recipient_id=%s file=%s",
                recipient_id,
                result.path,
            )
            raise
        await cls.cleanup_old_backups()
        logger.info(
            "Daily backup completed file=%s size_bytes=%s",
            result.path,
            result.size_bytes,
        )
        return result

    @classmethod
    async def create_database_backup(cls, *, created_at: datetime) -> BackupResult:
        backup_dir = settings.backup_directory_path
        backup_dir.mkdir(parents=True, exist_ok=True)
        filename = f"backup_{created_at.strftime('%Y-%m-%d_%H-%M')}.sql.gz"
        output_path = backup_dir / filename
        temp_path = output_path.with_suffix(".sql.gz.tmp")

        command = [
            settings.BACKUP_PGDUMP_PATH,
            "-h",
            settings.POSTGRES_HOST,
            "-p",
            str(settings.POSTGRES_PORT),
            "-U",
            settings.POSTGRES_USER,
            "-d",
            settings.POSTGRES_DB,
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            "--format=plain",
        ]
        env = os.environ.copy()
        env["PGPASSWORD"] = settings.POSTGRES_PASSWORD

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError as exc:
            logger.error("pg_dump executable not found backup_pgdump_path=%s", settings.BACKUP_PGDUMP_PATH)
            raise RuntimeError("pg_dump executable not found") from exc

        try:
            with gzip.open(temp_path, "wb") as compressed:
                assert process.stdout is not None
                while True:
                    chunk = await process.stdout.read(65536)
                    if not chunk:
                        break
                    compressed.write(chunk)

            stderr = b""
            if process.stderr is not None:
                stderr = await process.stderr.read()
            return_code = await process.wait()
            if return_code != 0:
                error_text = stderr.decode("utf-8", errors="ignore").strip()
                logger.error(
                    "pg_dump failed return_code=%s stderr=%s",
                    return_code,
                    error_text[:500],
                )
                raise RuntimeError("pg_dump failed")

            temp_path.replace(output_path)
            size_bytes = output_path.stat().st_size
            logger.info("Database backup created file=%s size_bytes=%s", output_path, size_bytes)
            return BackupResult(path=output_path, size_bytes=size_bytes, created_at=created_at)
        except Exception:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise

    @classmethod
    async def send_backup(cls, *, bot: Bot, recipient_id: int, result: BackupResult) -> None:
        caption = (
            "Daily backup completed.\n"
            f"Time: {result.created_at.strftime('%Y-%m-%d %H:%M %Z')}\n"
            f"File: {result.path.name}\n"
            f"Size: {cls.format_size(result.size_bytes)}\n"
            "Status: success"
        )
        document = FSInputFile(path=str(result.path), filename=result.path.name)
        last_error: Exception | None = None
        for attempt in range(1, 3):
            try:
                await bot.send_document(chat_id=recipient_id, document=document, caption=caption)
                logger.info(
                    "Backup file sent to recipient recipient_id=%s file=%s attempt=%s",
                    recipient_id,
                    result.path.name,
                    attempt,
                )
                return
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Backup send attempt failed recipient_id=%s file=%s attempt=%s",
                    recipient_id,
                    result.path.name,
                    attempt,
                    exc_info=True,
                )
                if attempt == 1:
                    await asyncio.sleep(3)
        assert last_error is not None
        raise last_error

    @classmethod
    async def cleanup_old_backups(cls) -> None:
        backup_dir = settings.backup_directory_path
        if not backup_dir.exists():
            return
        files = sorted(
            backup_dir.glob("backup_*.sql.gz"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        keep_count = max(settings.BACKUP_RETENTION_COUNT, 1)
        for old_file in files[keep_count:]:
            try:
                old_file.unlink(missing_ok=True)
                logger.info("Removed old backup file=%s", old_file)
            except Exception:
                logger.warning("Failed to remove old backup file=%s", old_file, exc_info=True)

    @staticmethod
    def format_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        if size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        return f"{size_bytes / (1024 * 1024):.2f} MB"
