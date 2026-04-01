from __future__ import annotations

from datetime import datetime, timezone
from fnmatch import fnmatch
import os
from pathlib import Path

import pytest
import pytest_asyncio

from app.core.config import settings
from app.services.backup.service import BackupResult, DailyBackupService


class FakeRedis:
    def __init__(self):
        self.strings = {}
        self.expires = {}

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.strings:
            return False
        self.strings[key] = value
        if ex is not None:
            self.expires[key] = ex
        return True

    async def get(self, key):
        return self.strings.get(key)

    async def exists(self, key):
        return 1 if key in self.strings else 0

    async def delete(self, *keys):
        removed = 0
        for key in keys:
            if key in self.strings:
                self.strings.pop(key, None)
                self.expires.pop(key, None)
                removed += 1
        return removed

    async def scan_iter(self, match=None):
        for key in list(self.strings.keys()):
            if match is None or fnmatch(key, match):
                yield key


@pytest_asyncio.fixture(autouse=True)
async def fake_redis():
    redis = FakeRedis()
    await DailyBackupService.set_client_for_tests(redis)
    yield redis
    await DailyBackupService.set_client_for_tests(None)


def test_backup_recipient_prefers_explicit_recipient(monkeypatch):
    monkeypatch.setattr(settings, "BACKUP_RECIPIENT_TELEGRAM_ID", 555)
    monkeypatch.setattr(settings, "ADMIN_IDS", "111,222")
    assert DailyBackupService.resolve_recipient_id() == 555


@pytest.mark.asyncio
async def test_cleanup_old_backups_keeps_recent_files(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "BACKUP_DIRECTORY", str(tmp_path))
    monkeypatch.setattr(settings, "BACKUP_RETENTION_COUNT", 2)

    files: list[Path] = []
    for index in range(3):
        path = tmp_path / f"backup_2026-04-0{index + 1}_03-00.sql.gz"
        path.write_bytes(f"backup-{index}".encode("utf-8"))
        files.append(path)

    oldest, middle, newest = files
    os.utime(oldest, (1, 1))
    os.utime(middle, (2, 2))
    os.utime(newest, (3, 3))

    await DailyBackupService.cleanup_old_backups()

    assert not oldest.exists()
    assert middle.exists()
    assert newest.exists()


@pytest.mark.asyncio
async def test_scheduler_marks_day_after_success(monkeypatch):
    monkeypatch.setattr(settings, "BACKUP_ENABLED", True)
    monkeypatch.setattr(settings, "BACKUP_RECIPIENT_TELEGRAM_ID", 999)
    monkeypatch.setattr(settings, "BACKUP_SCHEDULE_TIME", "00:00")
    monkeypatch.setattr(settings, "BACKUP_TIMEZONE", "UTC")

    calls = []

    async def fake_create_and_send_backup(*, bot, recipient_id, now_local=None):
        calls.append(recipient_id)
        return BackupResult(
            path=Path("backup_2026-04-01_03-00.sql.gz"),
            size_bytes=1024,
            created_at=now_local or datetime.now(timezone.utc),
        )

    monkeypatch.setattr(DailyBackupService, "create_and_send_backup", fake_create_and_send_backup)

    ran_first = await DailyBackupService.maybe_run_scheduled_backup(bot=object())
    ran_second = await DailyBackupService.maybe_run_scheduled_backup(bot=object())

    assert ran_first is True
    assert ran_second is False
    assert calls == [999]
