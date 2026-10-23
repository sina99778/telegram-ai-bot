# Database backup on the production host

`scripts/backup_database.sh` is the host-side backup script for the `telegram-ai-bot-db-1` PostgreSQL container. It backs up the application database `gemini_bot_db`, rather than the empty administrative database `postgres`.

Install it with `install -m 700 scripts/backup_database.sh /root/backup_bot.sh` as root. The existing production root crontab invokes `/root/backup_bot.sh` daily at 03:00 UTC. Backups are stored under `/root/bot_backups` with restrictive permissions. The script serializes runs with flock, produces a compressed custom-format archive in a temporary file, checks the archive with pg_restore, and renames it only after success. Existing backups are not deleted; choose a retention policy separately.

Validation on 2026-10-24 (Europe/Berlin): `bash -n` passed; a roughly 18 MiB archive was restored using `pg_restore --exit-on-error` into a disposable PostgreSQL 15 container, with 11 public tables present. Neither the production database nor its volumes were replaced during validation. Keep an off-host copy and validate restores regularly.
