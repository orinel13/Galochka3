from aiogram.fsm.state import State, StatesGroup


class TextToAudioState(StatesGroup):
    waiting_text = State()


class TextPhotoVideoState(StatesGroup):
    waiting_photo = State()
    waiting_text = State()


class AudioPhotoVideoState(StatesGroup):
    waiting_photo = State()
    waiting_audio = State()


class GeneratedAudioVideoState(StatesGroup):
    waiting_photo = State()


class VoiceCloneState(StatesGroup):
    waiting_name = State()
    waiting_audio = State()
