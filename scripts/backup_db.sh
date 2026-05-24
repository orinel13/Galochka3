#!/usr/bin/env bash
set -euo pipefail

DB_PATH="${DATABASE_PATH:-./data/galochka.db}"
BACKUP_DIR="./data/backups"
mkdir -p "$BACKUP_DIR"

if [ ! -f "$DB_PATH" ]; then
  echo "Database not found: $DB_PATH" >&2
  exit 1
fi

STAMP="$(date -u +%Y%m%d%H%M%S)"
BACKUP_PATH="$BACKUP_DIR/galochka_$STAMP.db"
sqlite3 "$DB_PATH" ".backup '$BACKUP_PATH'"
echo "Backup created: $BACKUP_PATH"
