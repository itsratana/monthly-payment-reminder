import asyncio
import logging

from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram.fsm.storage.memory import MemoryStorage

import config
from database.schema import init_db

from handlers.start import router as start_router
from handlers.join import router as join_router
from handlers.dashboard import router as dashboard_router
from handlers.payment_create import router as payment_create_router
from handlers.payments import router as payments_router
from handlers.payment_members import router as payment_members_router
from handlers.payment_status import router as payment_status_router

from scheduler.reminder_scheduler import run_reminder_tick



logger = logging.getLogger(__name__)


dp = Dispatcher(storage=MemoryStorage())

from handlers.navigation import router as navigation_router
from handlers.settings import router as settings_router
from handlers.status import router as status_router
from handlers.fallback import router as fallback_router
from handlers.middleware import InteractionMiddleware

interaction = InteractionMiddleware()
dp.message.outer_middleware(interaction)
dp.callback_query.outer_middleware(interaction)
dp.include_router(navigation_router)
dp.include_router(start_router)
dp.include_router(join_router)
dp.include_router(dashboard_router)
dp.include_router(payment_create_router)
dp.include_router(payments_router)
dp.include_router(payment_members_router)
dp.include_router(payment_status_router)
dp.include_router(settings_router)
dp.include_router(status_router)
dp.include_router(fallback_router)


async def main():
    from services.runtime_service import instance_lock, validate_storage, observe_telegram, startup_probe
    from services.health_service import configure_health, write_health
    from aiogram.client.session.aiohttp import AiohttpSession
    from scheduler.reminder_scheduler import _tick_lock

    config.validate_config()
    from services.logging_service import configure_logging
    configure_logging(config.LOG_LEVEL, config.BOT_TOKEN)
    path = validate_storage(config.DATABASE_PATH, config.DATABASE_REQUIRE_EXISTING)
    with instance_lock(path, config.BOT_TOKEN):
        bot = None
        scheduler = None
        configure_health(config.HEALTH_PATH)
        try:
            init_db()
            from database.connection import check_integrity
            check_integrity()
            path.chmod(0o600)
            bot = Bot(config.BOT_TOKEN, session=AiohttpSession(timeout=30))
            bot.session.middleware(observe_telegram)
            await startup_probe(bot)
            # Initial tick ensures health includes a real scheduler evaluation.
            await run_reminder_tick(bot)
            scheduler = AsyncIOScheduler(timezone=config.APP_TIMEZONE)
            scheduler.add_job(run_reminder_tick, 'interval', seconds=config.REMINDER_CHECK_SECONDS,
                              args=[bot], max_instances=1, coalesce=True, misfire_grace_time=30)
            scheduler.start()
            write_health(ready=True)
            logger.info('Bot ready; single scheduler owner')
            # Serial update handling gives shutdown a bounded in-flight handler.
            await dp.start_polling(bot, handle_as_tasks=False, close_bot_session=False)
        finally:
            write_health(ready=False)
            if scheduler and scheduler.running:
                scheduler.pause()
                # Wait for the current send to finish before canceling scheduler jobs.
                try:
                    await asyncio.wait_for(_tick_lock.acquire(), timeout=35)
                    _tick_lock.release()
                except asyncio.TimeoutError:
                    logger.warning('Shutdown deadline reached; reserved attempts need reconciliation')
                scheduler.shutdown(wait=False)
                await asyncio.sleep(0)
            if bot:
                await bot.session.close()
            logger.info('Bot stopped')


if __name__ == "__main__":
    asyncio.run(main())
