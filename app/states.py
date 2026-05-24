from aiogram.fsm.state import State, StatesGroup


class TextToAudioState(StatesGroup):
    waiting_text = State()


class TextPhotoVideoState(StatesGroup):
    waiting_photo = State()
    waiting_text = State()
    waiting_prompt_choice = State()
    waiting_prompt_text = State()


class AudioPhotoVideoState(StatesGroup):
    waiting_photo = State()
    waiting_audio = State()
    waiting_prompt_choice = State()
    waiting_prompt_text = State()


class GeneratedAudioVideoState(StatesGroup):
    waiting_photo = State()
    waiting_prompt_choice = State()
    waiting_prompt_text = State()


class ImageToVideoState(StatesGroup):
    waiting_photo = State()
    waiting_prompt_choice = State()
    waiting_prompt_text = State()


class TextToImageState(StatesGroup):
    waiting_prompt = State()


class ImageEditState(StatesGroup):
    waiting_image = State()
    waiting_prompt = State()


class VoiceCloneState(StatesGroup):
    waiting_name = State()
    waiting_audio = State()
