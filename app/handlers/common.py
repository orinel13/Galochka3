from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from app.config import Settings
from app.db import Database
from app.keyboards import access_decision_keyboard, main_menu
from app.ui_messages import send_tracked_message, track_ui_message
from app.utils import format_user

router = Router()


@router.message(CommandStart())
async def start(message: Message, db: Database, settings: Settings) -> None:
    tg = message.from_user
    if not tg:
        sent = await message.answer("Не удалось определить пользователя.")
        track_ui_message(sent.chat.id, sent.message_id)
        return
    is_admin = tg.id == settings.admin_telegram_id
    user = await db.upsert_user(tg.id, tg.username, tg.first_name, tg.last_name, is_admin, settings.allow_new_users)
    if user["is_allowed"] or user["is_admin"]:
        sent = await message.answer("Доступ активен. Выбери действие.", reply_markup=main_menu())
        track_ui_message(sent.chat.id, sent.message_id)
        return
    request_id = await db.create_pending_access_request(tg.id, tg.username, tg.first_name, tg.last_name)
    sent = await message.answer("Заявка отправлена администратору. Дождись подтверждения.")
    track_ui_message(sent.chat.id, sent.message_id)
    if request_id is not None:
        text = "Новая заявка на доступ\n" + format_user(tg.id, tg.username, tg.first_name, tg.last_name)
        await message.bot.send_message(settings.admin_telegram_id, text, reply_markup=access_decision_keyboard(tg.id))


@router.callback_query(lambda c: c.data and c.data.startswith("access_"))
async def access_decision(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.from_user or callback.from_user.id != settings.admin_telegram_id:
        await callback.answer("Недоступно.", show_alert=True)
        return
    action, raw_id = callback.data.split(":", 1)
    telegram_id = int(raw_id)
    approved = action == "access_allow"
    await db.decide_access(telegram_id, approved, settings.admin_telegram_id)
    if approved:
        await callback.message.edit_text(f"Доступ выдан пользователю {telegram_id}.")
        await send_tracked_message(callback.bot, telegram_id, "Доступ выдан. Нажми /start, чтобы открыть меню.")
    else:
        await callback.message.edit_text(f"Заявка пользователя {telegram_id} отклонена.")
        await send_tracked_message(callback.bot, telegram_id, "Доступ не выдан.")
    await callback.answer("Готово.")


@router.callback_query(lambda c: c.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()
