from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import ensure_data_dirs, load_settings
from app.db import Database


async def main() -> None:
    settings = load_settings(require_secrets=False)
    ensure_data_dirs(settings)
    db = Database(settings.database_path)
    await db.connect()
    await db.init_schema()
    await db.close()
    print(f"SQLite initialized: {settings.database_path}")
    print(f"Data directories ready: {settings.data_dir}, {settings.tmp_dir}, {settings.log_file.parent}")


if __name__ == "__main__":
    asyncio.run(main())
