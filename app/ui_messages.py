from __future__ import annotations

from collections import defaultdict
from typing import Any

from aiogram import Bot
from aiogram.types import Message


_TRACKED_MESSAGE_IDS: dict[int, set[int]] = defaultdict(set)


def track_ui_message(chat_id: int, message_id: int) -> None:
    _TRACKED_MESSAGE_IDS[chat_id].add(message_id)


async def send_tracked_message(bot: Bot, chat_id: int, text: str, **kwargs: Any) -> Message:
    sent = await bot.send_message(chat_id, text, **kwargs)
    track_ui_message(sent.chat.id, sent.message_id)
    return sent


async def delete_tracked_messages(bot: Bot, chat_id: int) -> None:
    ids = list(_TRACKED_MESSAGE_IDS.pop(chat_id, set()))
    for message_id in ids:
        try:
            await bot.delete_message(chat_id, message_id)
        except Exception:
            pass
