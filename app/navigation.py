from __future__ import annotations

import json
from typing import Any

from app.db import Database
from app.utils import now_iso


BACK_LABEL = "⬅️ Назад"
MENU_LABEL = "🏠 Меню"
BACK_TEXTS = {BACK_LABEL, "Назад", "назад"}
MENU_TEXTS = {MENU_LABEL, "Меню", "меню", "/menu", "/start"}


async def push_screen(db: Database, user_id: int, screen_name: str, payload: dict[str, Any] | None = None) -> None:
    stack = await _get_stack(db, user_id)
    stack.append({"screen": screen_name, "payload": payload or {}})
    await _save_stack(db, user_id, stack)


async def pop_screen(db: Database, user_id: int) -> dict[str, Any] | None:
    stack = await _get_stack(db, user_id)
    if not stack:
        return None
    screen = stack.pop()
    await _save_stack(db, user_id, stack)
    return screen


async def clear_stack(db: Database, user_id: int) -> None:
    await _save_stack(db, user_id, [])


async def render_screen(user_id: int, screen_name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"telegram_id": user_id, "screen": screen_name, "payload": payload or {}}


async def universal_back_handler(db: Database, user_id: int) -> dict[str, Any] | None:
    return await pop_screen(db, user_id)


async def _get_stack(db: Database, user_id: int) -> list[dict[str, Any]]:
    row = await db.fetchone("SELECT stack_json FROM user_navigation WHERE telegram_id=?", (user_id,))
    if not row:
        return []
    try:
        data = json.loads(row["stack_json"])
        return data if isinstance(data, list) else []
    except ValueError:
        return []


async def _save_stack(db: Database, user_id: int, stack: list[dict[str, Any]]) -> None:
    await db.execute(
        """
        INSERT INTO user_navigation (telegram_id, stack_json, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET stack_json=excluded.stack_json, updated_at=excluded.updated_at
        """,
        (user_id, json.dumps(stack, ensure_ascii=False), now_iso()),
    )
