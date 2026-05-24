from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


TEXT_TO_AUDIO = "🎙 Текст → аудио"
TEXT_PHOTO_TO_VIDEO = "🖼 Текст + фото → видео"
AUDIO_PHOTO_TO_VIDEO = "🎧 Аудио + фото → видео"
VOICE_MENU = "🎭 Голос"
BALANCE = "📊 Баланс"
MY_JOBS = "🕘 Мои задачи"
HELP = "ℹ️ Помощь"


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=TEXT_TO_AUDIO), KeyboardButton(text=TEXT_PHOTO_TO_VIDEO)],
            [KeyboardButton(text=AUDIO_PHOTO_TO_VIDEO), KeyboardButton(text=VOICE_MENU)],
            [KeyboardButton(text=BALANCE), KeyboardButton(text=MY_JOBS)],
            [KeyboardButton(text=HELP)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие",
    )


def access_decision_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Разрешить", callback_data=f"access_allow:{telegram_id}"),
                InlineKeyboardButton(text="Отклонить", callback_data=f"access_deny:{telegram_id}"),
            ]
        ]
    )


def audio_result_keyboard(job_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🖼 Сделать видео из этого аудио", callback_data=f"audio_to_video:{job_id}")],
            [
                InlineKeyboardButton(text="🔁 Повторить аудио", callback_data=f"repeat_audio:{job_id}"),
                InlineKeyboardButton(text="🎭 Сменить голос", callback_data="open_setvoice"),
            ],
            [InlineKeyboardButton(text="🗑 Удалить результат", callback_data=f"delete_result:{job_id}")],
        ]
    )


def choose_voice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎭 Выбрать голос", callback_data="open_setvoice")],
        ]
    )


def job_history_keyboard(job_id: int, job_type: str, has_local_file: bool) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    if job_type == "tts":
        buttons.append([InlineKeyboardButton(text="🖼 Сделать видео", callback_data=f"audio_to_video:{job_id}")])
    if has_local_file:
        buttons.append([InlineKeyboardButton(text="🗑 Удалить результат", callback_data=f"delete_result:{job_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons or [[InlineKeyboardButton(text="Закрыть", callback_data="noop")]])


def voices_keyboard(voices: list[dict[str, str]]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=voice["name"], callback_data=f"setvoice:{voice['hedra_voice_id']}")]
        for voice in voices
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows or [[InlineKeyboardButton(text="Нет голосов", callback_data="noop")]])
