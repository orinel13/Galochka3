from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


TEXT_TO_AUDIO = "🎙 Текст → аудио"
TEXT_PHOTO_TO_VIDEO = "Текст + фото → avatar video"
AUDIO_PHOTO_TO_VIDEO = "Аудио + фото → avatar video"
GENERATED_AUDIO_TO_VIDEO = "Сгенерированное аудио + фото → avatar video"
IMAGE_TO_VIDEO = "Фото → видео без аудио"
TEXT_TO_IMAGE = "Текст → изображение"
IMAGE_EDIT = "Редактировать изображение"
VOICE_MENU = "🎭 Голос"
VOICE_SELECT = "Выбрать голос"
VOICE_CURRENT = "Мой текущий голос"
VOICE_LIST = "Список голосов"
BALANCE = "📊 Баланс"
MY_JOBS = "🕘 Мои задачи"
HELP = "ℹ️ Помощь"
AUDIO_SECTION = "🎙 Аудио"
VIDEO_SECTION = "🎬 Видео"
IMAGE_SECTION = "🖼 Изображения"
SETTINGS_SECTION = "⚙️ Настройки"
BACK = "Назад"


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=AUDIO_SECTION), KeyboardButton(text=VIDEO_SECTION)],
            [KeyboardButton(text=IMAGE_SECTION), KeyboardButton(text=VOICE_MENU)],
            [KeyboardButton(text=BALANCE), KeyboardButton(text=MY_JOBS)],
            [KeyboardButton(text=SETTINGS_SECTION), KeyboardButton(text=HELP)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие",
    )


def audio_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=TEXT_TO_AUDIO)], [KeyboardButton(text="История аудио")], [KeyboardButton(text=BACK)]],
        resize_keyboard=True,
    )


def video_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text=TEXT_PHOTO_TO_VIDEO)],
        [KeyboardButton(text=AUDIO_PHOTO_TO_VIDEO)],
        [KeyboardButton(text=GENERATED_AUDIO_TO_VIDEO)],
        [KeyboardButton(text=IMAGE_TO_VIDEO)],
        [KeyboardButton(text="Prompt для видео")],
        [KeyboardButton(text=BACK)],
    ]
    if is_admin:
        keyboard.insert(4, [KeyboardButton(text="Выбрать video model"), KeyboardButton(text="Выбрать avatar model")])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )


def image_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text=TEXT_TO_IMAGE)],
        [KeyboardButton(text=IMAGE_EDIT)],
        [KeyboardButton(text="Prompt для изображения")],
        [KeyboardButton(text=BACK)],
    ]
    if is_admin:
        keyboard.insert(2, [KeyboardButton(text="Выбрать image model")])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )


def voice_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=VOICE_SELECT), KeyboardButton(text=VOICE_CURRENT)],
            [KeyboardButton(text=VOICE_LIST)],
            [KeyboardButton(text=BACK)],
        ],
        resize_keyboard=True,
    )


def settings_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Текущие параметры")],
            [KeyboardButton(text="Video aspect ratio"), KeyboardButton(text="Video resolution")],
            [KeyboardButton(text="Image aspect ratio"), KeyboardButton(text="Image resolution")],
            [KeyboardButton(text="TTS speed"), KeyboardButton(text="TTS stability")],
            [KeyboardButton(text="Очистить временные результаты")],
            [KeyboardButton(text=BACK)],
        ],
        resize_keyboard=True,
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


def scenario_keyboard(
    scenario: str,
    include_voice: bool = False,
    include_model: bool = True,
    include_prompt: bool = True,
) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="Продолжить", callback_data=f"scenario_continue:{scenario}")]]
    extra: list[InlineKeyboardButton] = []
    if include_voice:
        extra.append(InlineKeyboardButton(text="Изменить голос", callback_data="open_setvoice"))
    if include_model:
        extra.append(InlineKeyboardButton(text="Изменить модель", callback_data=f"scenario_model:{scenario}"))
    if include_prompt:
        extra.append(InlineKeyboardButton(text="Изменить prompt", callback_data=f"scenario_prompt:{scenario}"))
    if extra:
        rows.append(extra[:2])
        if len(extra) > 2:
            rows.append(extra[2:])
    rows.append([InlineKeyboardButton(text="Назад", callback_data="scenario_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def prompt_choice_keyboard(scenario: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Пропустить", callback_data=f"prompt_skip:{scenario}")],
            [InlineKeyboardButton(text="Написать prompt", callback_data=f"prompt_write:{scenario}")],
            [InlineKeyboardButton(text="Prompt по умолчанию", callback_data=f"prompt_default:{scenario}")],
        ]
    )


def options_keyboard(kind: str, values: list[str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=value, callback_data=f"option:{kind}:{value}")] for value in values]
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


def video_models_keyboard(models: list[dict[str, str]], selected_id: str | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, model in enumerate(models, start=1):
        marker = "✅ " if model["id"] == selected_id else ""
        rows.append([InlineKeyboardButton(text=f"{marker}{model['name']}", callback_data=f"set_video_model:{index}")])
    return InlineKeyboardMarkup(inline_keyboard=rows or [[InlineKeyboardButton(text="Модели не найдены", callback_data="noop")]])


def user_models_keyboard(family: str, models: list[dict[str, str]], selected_id: str | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, model in enumerate(models, start=1):
        marker = "✅ " if model["id"] == selected_id else ""
        premium = " premium" if model.get("premium") else ""
        rows.append([InlineKeyboardButton(text=f"{marker}{model['name']}{premium}", callback_data=f"user_model:{family}:{index}")])
    return InlineKeyboardMarkup(inline_keyboard=rows or [[InlineKeyboardButton(text="Нет доступных моделей", callback_data="noop")]])
