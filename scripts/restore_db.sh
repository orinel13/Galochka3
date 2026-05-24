#!/usr/bin/env bash
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: scripts/restore_db.sh ./data/backups/galochka_YYYYMMDDHHMMSS.db" >&2
  exit 1
fi

BACKUP_PATH="$1"
DB_PATH="${DATABASE_PATH:-./data/galochka.db}"

if [ ! -f "$BACKUP_PATH" ]; then
  echo "Backup not found: $BACKUP_PATH" >&2
  exit 1
fi

mkdir -p "$(dirname "$DB_PATH")"
cp "$DB_PATH" "$DB_PATH.before_restore.$(date -u +%Y%m%d%H%M%S)" 2>/dev/null || true
cp "$BACKUP_PATH" "$DB_PATH"
echo "Database restored to: $DB_PATH"
