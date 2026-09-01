import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import ErrorEvent, Message

from ..core.config import settings
from ..db.database import close_db, init_db, migrate_schema
from ..services.morning_report import send_morning_reports
from ..utils import phrases
from ..utils.helpers import get_msk_now
from .handlers.categories import router as categories_router
from .handlers.evening_flow import router as evening_router
from .handlers.history import router as history_router
from .handlers.menu import router as menu_router
from .handlers.monthly_summary import router as monthly_summary_router
from .handlers.test_commands import router as test_router
from .middleware import (
    AutoTrackOutgoingMiddleware,
    KeyboardCleanupMiddleware,
    RateLimitMiddleware,
    dup_middleware,
)
from .scheduler import setup_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(
    token=settings.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
bot.session.middleware(AutoTrackOutgoingMiddleware())
dp = Dispatcher()
dp.message.middleware(KeyboardCleanupMiddleware())
dp.message.middleware(RateLimitMiddleware())
dp.message.middleware(dup_middleware)
dp.callback_query.middleware(KeyboardCleanupMiddleware())
dp.callback_query.middleware(RateLimitMiddleware())

dp.include_router(categories_router)
dp.include_router(test_router)
dp.include_router(evening_router)
dp.include_router(history_router)
dp.include_router(monthly_summary_router)
dp.include_router(menu_router)


@dp.errors()
async def error_handler(event: ErrorEvent):
    logger.error("Unhandled exception", exc_info=event.exception)

    update = event.update
    msg: Message | None = None
    if hasattr(update, "message"):
        msg = update.message
    elif hasattr(update, "callback_query") and update.callback_query:
        msg = update.callback_query.message

    if msg:
        try:
            await msg.answer(phrases.ERR_GENERIC)
        except Exception:
            pass


async def on_startup():
    logger.info("Initializing database...")
    await init_db()
    logger.info("Migrating schema...")
    await migrate_schema()
    setup_scheduler(bot, dp.storage)
    msk_now = get_msk_now()
    if 5 <= msk_now.hour < 12:
        logger.info("Старт в утреннем окне — запускаю morning report (если не отправлен)")
        asyncio.create_task(send_morning_reports(bot))
    asyncio.create_task(dup_middleware.start_cleanup())
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
