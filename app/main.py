from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from app.config import ensure_data_dirs, load_settings
from app.db import Database
from app.files import FilesService
from app.handlers import admin, common, user
from app.hedra_client import HedraClient
from app.jobs import JobManager
from app.services.cleanup_service import CleanupService
from app.services.credits_service import CreditsService
from app.services.model_service import ModelService
from app.services.voice_clone_service import VoiceCloneService
from app.utils import setup_logging

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = load_settings(require_secrets=True)
    ensure_data_dirs(settings)
    setup_logging(settings.log_file)

    db = Database(settings.database_path)
    await db.connect()
    await db.init_schema()

    bot = Bot(settings.bot_token)
    hedra = HedraClient(settings.hedra_api_key, settings.hedra_base_url)
    files = FilesService(settings, bot)
    model_service = ModelService(db, hedra)
    credits_service = CreditsService(db, hedra)
    cleanup_service = CleanupService(db, settings)
    voice_clone_service = VoiceCloneService(db, hedra, settings.job_poll_interval_sec, settings.job_timeout_sec)
    jobs = JobManager(db, settings, bot, hedra, files, model_service, credits_service)

    dp = Dispatcher(storage=MemoryStorage())
    dp["settings"] = settings
    dp["db"] = db
    dp["hedra"] = hedra
    dp["files"] = files
    dp["models"] = model_service
    dp["credits"] = credits_service
    dp["cleanup"] = cleanup_service
    dp["voice_clone"] = voice_clone_service
    dp["jobs"] = jobs

    dp.include_router(common.router)
    dp.include_router(admin.router)
    dp.include_router(user.router)

    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Запуск и заявка на доступ"),
            BotCommand(command="voices", description="Список голосов"),
            BotCommand(command="setvoice", description="Выбрать голос"),
            BotCommand(command="balance", description="Баланс Hedra"),
            BotCommand(command="help", description="Помощь"),
            BotCommand(command="admin", description="Админ-команды"),
        ]
    )

    await jobs.start()
    cleanup_service.start()
    logger.info("Galochka 3 Hedra bot started")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        logger.info("Stopping bot")
        await cleanup_service.stop()
        await jobs.stop()
        await hedra.close()
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
