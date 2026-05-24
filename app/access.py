from __future__ import annotations

from aiogram.types import Message

from app.config import Settings
from app.db import Database


async def is_admin(settings: Settings, telegram_id: int | None) -> bool:
    return telegram_id is not None and telegram_id == settings.admin_telegram_id


async def ensure_allowed(message: Message, db: Database, settings: Settings) -> bool:
    user = message.from_user
    if not user:
        await message.answer("Не удалось определить пользователя.")
        return False
    if user.id == settings.admin_telegram_id:
        return True
    row = await db.get_user(user.id)
    if row and row["is_allowed"]:
        return True
    await message.answer("Доступ не выдан. Напиши /start, чтобы отправить заявку администратору.")
    return False


async def ensure_admin(message: Message, settings: Settings) -> bool:
    user = message.from_user
    if user and user.id == settings.admin_telegram_id:
        return True
    await message.answer("Команда доступна только администратору.")
    return False
