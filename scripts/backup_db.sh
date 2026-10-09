#!/bin/bash
# Ежедневный бэкап БД (Neon) → локально (VPS).
#
# Cron:
#   0 3 * * * /opt/my-app/scripts/backup_db.sh >> /var/log/db_backup.log 2>&1
#
# Retention: 30 дней.

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/opt/my-app/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
DATABASE_URL="${DATABASE_URL:-}"

if [ -z "$DATABASE_URL" ]; then
    if [ -f /opt/my-app/.env ]; then
        DATABASE_URL=$(grep -E '^DATABASE_URL=' /opt/my-app/.env | cut -d= -f2-)
    fi
fi

if [ -z "$DATABASE_URL" ]; then
    echo "ERROR: DATABASE_URL not set"
    exit 1
fi

CLEAN_URL="${DATABASE_URL/postgresql+asyncpg:\/\//postgresql://}"

DATE=$(date +%Y-%m-%d_%H-%M-%S)
FILE="$BACKUP_DIR/db_$DATE.dump.gz"

mkdir -p "$BACKUP_DIR"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup started: $FILE"

pg_dump --no-owner --no-acl --format=custom "$CLEAN_URL" | gzip > "$FILE"

SIZE=$(du -h "$FILE" | cut -f1)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup done: $FILE ($SIZE)"

DELETED=$(find "$BACKUP_DIR" -name "db_*.dump.gz" -mtime +$RETENTION_DAYS -print -delete | wc -l)
if [ "$DELETED" -gt 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Deleted $DELETED old backups"
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup finished"
