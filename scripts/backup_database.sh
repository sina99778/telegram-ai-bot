#!/bin/bash
set -euo pipefail
umask 077

# Serialize manual and scheduled runs; never prune existing backups here.
exec 9>/run/lock/telegram-ai-bot-backup.lock
flock -n 9 || exit 0
BACKUP_DIR=/root/bot_backups
mkdir -p "$BACKUP_DIR"
FILE_NAME="gemini_bot_db_$(date -u +%Y%m%d_%H%M%S).dump"
TEMP_FILE=$(mktemp "$BACKUP_DIR/.backup.XXXXXX")
trap 'rm -f -- "$TEMP_FILE"' EXIT

docker exec telegram-ai-bot-db-1 pg_dump -U postgres -d gemini_bot_db -Fc > "$TEMP_FILE"
test -s "$TEMP_FILE"
# Validate archive readability before publishing a successful backup.
docker exec -i telegram-ai-bot-db-1 pg_restore --list < "$TEMP_FILE" > /dev/null
mv -- "$TEMP_FILE" "$BACKUP_DIR/$FILE_NAME"
trap - EXIT
printf 'Backup completed: %s\n' "$BACKUP_DIR/$FILE_NAME"
