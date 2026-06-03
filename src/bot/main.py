import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .handlers.menu import router as menu_router
from .handlers.history import router as history_router
from .handlers.test_commands import router as test_router
from .handlers.evening_flow import router as evening_router
from .middleware import RateLimitMiddleware
from ..core.config import settings
from ..db.database import init_db, close_db, engine, migrate_schema
from .scheduler import setup_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(
    token=settings.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()
dp.message.middleware(RateLimitMiddleware())
dp.callback_query.middleware(RateLimitMiddleware())

dp.include_router(test_router)
dp.include_router(evening_router)
dp.include_router(history_router)
dp.include_router(menu_router)


async def on_startup():
    logger.info("Initializing database...")
    await init_db()
    logger.info("Migrating schema...")
    await migrate_schema()
    setup_scheduler(bot, dp.storage)
    logger.info("Bot started!")


async def on_shutdown():
    logger.info("Shutting down...")
    stop_scheduler()
    await close_db()
    await bot.session.close()


async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
