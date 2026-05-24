from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import aiosqlite

from app.utils import now_iso


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
  telegram_id INTEGER PRIMARY KEY,
  username TEXT,
  first_name TEXT,
  last_name TEXT,
  is_allowed INTEGER NOT NULL DEFAULT 0,
  is_admin INTEGER NOT NULL DEFAULT 0,
  selected_voice_id TEXT,
  selected_voice_name TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS access_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  telegram_id INTEGER NOT NULL,
  username TEXT,
  first_name TEXT,
  last_name TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL,
  decided_at TEXT,
  decided_by INTEGER
);

CREATE TABLE IF NOT EXISTS voices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  hedra_voice_id TEXT NOT NULL UNIQUE,
  source TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1,
  is_default INTEGER NOT NULL DEFAULT 0,
  owner_label TEXT,
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS voice_clone_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  sample_asset_id TEXT,
  hedra_generation_id TEXT,
  resulting_voice_id TEXT,
  status TEXT NOT NULL,
  error_message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  telegram_id INTEGER NOT NULL,
  job_type TEXT NOT NULL,
  status TEXT NOT NULL,
  parent_job_id INTEGER,
  source_audio_job_id INTEGER,
  voice_id TEXT,
  voice_name TEXT,
  text TEXT,
  text_prompt TEXT,
  prompt_mode TEXT,
  duration_ms INTEGER,
  selected_model_id TEXT,
  selected_model_name TEXT,
  generation_family TEXT,
  input_image_asset_id TEXT,
  input_image_url TEXT,
  adapter_name TEXT,
  request_payload_keys TEXT,
  hedra_error_raw TEXT,
  image_file_id TEXT,
  audio_file_id TEXT,
  source_image_file_id TEXT,
  hedra_generation_id TEXT,
  hedra_asset_id TEXT,
  hedra_audio_asset_id TEXT,
  hedra_image_asset_id TEXT,
  result_url TEXT,
  result_download_url TEXT,
  result_streaming_url TEXT,
  local_result_path TEXT,
  error_message TEXT,
  expires_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT
);

CREATE TABLE IF NOT EXISTS hedra_models (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  type TEXT,
  supports_1_1 INTEGER DEFAULT 0,
  supports_9_16 INTEGER DEFAULT 0,
  supports_16_9 INTEGER DEFAULT 0,
  supports_540p INTEGER DEFAULT 0,
  supports_720p INTEGER DEFAULT 0,
  supports_1080p INTEGER DEFAULT 0,
  supports_1440p INTEGER DEFAULT 0,
  supports_2160p INTEGER DEFAULT 0,
  requires_start_frame INTEGER DEFAULT 0,
  requires_end_frame INTEGER DEFAULT 0,
  requires_audio_input INTEGER DEFAULT 0,
  requires_input_video INTEGER DEFAULT 0,
  requires_duration_ms INTEGER DEFAULT 0,
  min_duration_ms INTEGER,
  max_duration_ms INTEGER,
  default_duration_ms INTEGER,
  allowed_duration_ms_json TEXT,
  supports_text_to_image INTEGER DEFAULT 0,
  supports_image_edit INTEGER DEFAULT 0,
  supports_reference_images INTEGER DEFAULT 0,
  requires_image_url INTEGER DEFAULT 0,
  supports_image_asset_id INTEGER DEFAULT 0,
  supports_data_uri INTEGER DEFAULT 0,
  supports_image_to_video INTEGER DEFAULT 0,
  supports_text_to_video INTEGER DEFAULT 0,
  billing_unit TEXT,
  credit_cost INTEGER,
  credits_per_second REAL,
  premium INTEGER DEFAULT 0,
  raw_json TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_settings (
  telegram_id INTEGER PRIMARY KEY,
  selected_avatar_model_id TEXT,
  selected_avatar_model_name TEXT,
  selected_video_model_id TEXT,
  selected_video_model_name TEXT,
  selected_image_model_id TEXT,
  selected_image_model_name TEXT,
  video_aspect_ratio TEXT DEFAULT '1:1',
  video_resolution TEXT DEFAULT '540p',
  image_aspect_ratio TEXT DEFAULT '1:1',
  image_resolution TEXT DEFAULT '1080p',
  video_duration_ms INTEGER DEFAULT 5000,
  tts_speed REAL DEFAULT 1.0,
  tts_stability REAL DEFAULT 0.5,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_navigation (
  telegram_id INTEGER PRIMARY KEY,
  stack_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS credit_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  remaining INTEGER,
  expiring INTEGER,
  used INTEGER,
  raw_json TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_user_created ON jobs (telegram_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status);
CREATE INDEX IF NOT EXISTS idx_access_pending ON access_requests (telegram_id, status);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()
            self.conn = None

    def _conn(self) -> aiosqlite.Connection:
        if not self.conn:
            raise RuntimeError("Database is not connected")
        return self.conn

    async def init_schema(self) -> None:
        await self._conn().executescript(SCHEMA_SQL)
        await self._conn().commit()
        await self._run_lightweight_migrations()

    async def execute(self, sql: str, params: Iterable[Any] = ()) -> aiosqlite.Cursor:
        cursor = await self._conn().execute(sql, tuple(params))
        await self._conn().commit()
        return cursor

    async def executemany(self, sql: str, params: Iterable[Iterable[Any]]) -> None:
        await self._conn().executemany(sql, params)
        await self._conn().commit()

    async def fetchone(self, sql: str, params: Iterable[Any] = ()) -> aiosqlite.Row | None:
        cur = await self._conn().execute(sql, tuple(params))
        row = await cur.fetchone()
        await cur.close()
        return row

    async def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[aiosqlite.Row]:
        cur = await self._conn().execute(sql, tuple(params))
        rows = await cur.fetchall()
        await cur.close()
        return rows

    async def upsert_user(
        self,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        is_admin: bool,
        allow_new_users: bool,
    ) -> aiosqlite.Row:
        now = now_iso()
        existing = await self.fetchone("SELECT * FROM users WHERE telegram_id=?", (telegram_id,))
        if existing:
            is_allowed = 1 if existing["is_allowed"] or is_admin else 0
            await self.execute(
                """
                UPDATE users
                SET username=?, first_name=?, last_name=?, is_admin=max(is_admin, ?),
                    is_allowed=max(is_allowed, ?), updated_at=?, last_seen_at=?
                WHERE telegram_id=?
                """,
                (username, first_name, last_name, int(is_admin), int(is_allowed), now, now, telegram_id),
            )
        else:
            await self.execute(
                """
                INSERT INTO users
                  (telegram_id, username, first_name, last_name, is_allowed, is_admin, created_at, updated_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    telegram_id,
                    username,
                    first_name,
                    last_name,
                    int(is_admin or allow_new_users),
                    int(is_admin),
                    now,
                    now,
                    now,
                ),
            )
        row = await self.fetchone("SELECT * FROM users WHERE telegram_id=?", (telegram_id,))
        if row is None:
            raise RuntimeError("User upsert failed")
        return row

    async def get_user(self, telegram_id: int) -> aiosqlite.Row | None:
        return await self.fetchone("SELECT * FROM users WHERE telegram_id=?", (telegram_id,))

    async def set_user_allowed(self, telegram_id: int, allowed: bool, admin: bool | None = None) -> None:
        now = now_iso()
        if admin is None:
            await self.execute(
                "UPDATE users SET is_allowed=?, updated_at=? WHERE telegram_id=?",
                (int(allowed), now, telegram_id),
            )
        else:
            await self.execute(
                "UPDATE users SET is_allowed=?, is_admin=?, updated_at=? WHERE telegram_id=?",
                (int(allowed), int(admin), now, telegram_id),
            )

    async def create_pending_access_request(
        self,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
    ) -> int | None:
        existing = await self.fetchone(
            "SELECT id FROM access_requests WHERE telegram_id=? AND status='pending' ORDER BY id DESC LIMIT 1",
            (telegram_id,),
        )
        if existing:
            return None
        cur = await self.execute(
            """
            INSERT INTO access_requests (telegram_id, username, first_name, last_name, status, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?)
            """,
            (telegram_id, username, first_name, last_name, now_iso()),
        )
        return cur.lastrowid

    async def decide_access(self, telegram_id: int, approved: bool, decided_by: int) -> None:
        status = "approved" if approved else "denied"
        now = now_iso()
        await self.execute(
            """
            UPDATE access_requests
            SET status=?, decided_at=?, decided_by=?
            WHERE telegram_id=? AND status='pending'
            """,
            (status, now, decided_by, telegram_id),
        )
        await self.set_user_allowed(telegram_id, approved)

    async def get_setting(self, key: str) -> str | None:
        row = await self.fetchone("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else None

    async def set_setting(self, key: str, value: str) -> None:
        await self.execute(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, value, now_iso()),
        )

    async def add_credit_snapshot(self, data: dict[str, Any]) -> None:
        remaining = _to_int(data.get("remaining") or data.get("credits_remaining") or data.get("balance"))
        expiring = _to_int(data.get("expiring") or data.get("credits_expiring"))
        used = _to_int(data.get("used") or data.get("credits_used"))
        await self.execute(
            "INSERT INTO credit_snapshots (remaining, expiring, used, raw_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (remaining, expiring, used, json.dumps(data, ensure_ascii=False), now_iso()),
        )

    async def get_user_settings(self, telegram_id: int) -> aiosqlite.Row:
        row = await self.fetchone("SELECT * FROM user_settings WHERE telegram_id=?", (telegram_id,))
        if row:
            return row
        await self.execute(
            "INSERT INTO user_settings (telegram_id, updated_at) VALUES (?, ?)",
            (telegram_id, now_iso()),
        )
        row = await self.fetchone("SELECT * FROM user_settings WHERE telegram_id=?", (telegram_id,))
        if row is None:
            raise RuntimeError("Failed to create user_settings")
        return row

    async def update_user_settings(self, telegram_id: int, **fields: Any) -> None:
        await self.get_user_settings(telegram_id)
        fields["updated_at"] = now_iso()
        assignments = ", ".join(f"{key}=?" for key in fields)
        await self.execute(f"UPDATE user_settings SET {assignments} WHERE telegram_id=?", [*fields.values(), telegram_id])

    async def _run_lightweight_migrations(self) -> None:
        await self._ensure_columns(
            "jobs",
            {
                "text_prompt": "TEXT",
                "prompt_mode": "TEXT",
                "duration_ms": "INTEGER",
                "selected_model_id": "TEXT",
                "selected_model_name": "TEXT",
                "generation_family": "TEXT",
                "input_image_asset_id": "TEXT",
                "input_image_url": "TEXT",
                "adapter_name": "TEXT",
                "request_payload_keys": "TEXT",
                "hedra_error_raw": "TEXT",
            },
        )
        await self._ensure_columns(
            "hedra_models",
            {
                "description": "TEXT",
                "supports_9_16": "INTEGER DEFAULT 0",
                "supports_16_9": "INTEGER DEFAULT 0",
                "supports_1080p": "INTEGER DEFAULT 0",
                "supports_1440p": "INTEGER DEFAULT 0",
                "supports_2160p": "INTEGER DEFAULT 0",
                "requires_start_frame": "INTEGER DEFAULT 0",
                "requires_end_frame": "INTEGER DEFAULT 0",
                "requires_audio_input": "INTEGER DEFAULT 0",
                "requires_input_video": "INTEGER DEFAULT 0",
                "requires_duration_ms": "INTEGER DEFAULT 0",
                "min_duration_ms": "INTEGER",
                "default_duration_ms": "INTEGER",
                "allowed_duration_ms_json": "TEXT",
                "supports_text_to_image": "INTEGER DEFAULT 0",
                "supports_image_edit": "INTEGER DEFAULT 0",
                "supports_reference_images": "INTEGER DEFAULT 0",
                "requires_image_url": "INTEGER DEFAULT 0",
                "supports_image_asset_id": "INTEGER DEFAULT 0",
                "supports_data_uri": "INTEGER DEFAULT 0",
                "supports_image_to_video": "INTEGER DEFAULT 0",
                "supports_text_to_video": "INTEGER DEFAULT 0",
                "billing_unit": "TEXT",
                "credit_cost": "INTEGER",
                "credits_per_second": "REAL",
                "premium": "INTEGER DEFAULT 0",
            },
        )
        await self._ensure_columns(
            "user_settings",
            {
                "video_duration_ms": "INTEGER DEFAULT 5000",
            },
        )

    async def _ensure_columns(self, table: str, columns: dict[str, str]) -> None:
        existing_rows = await self.fetchall(f"PRAGMA table_info({table})")
        existing = {row["name"] for row in existing_rows}
        for name, definition in columns.items():
            if name not in existing:
                await self.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _to_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
