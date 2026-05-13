import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .handlers.commands import router as handlers_router
from .handlers.budget import router as budget_router
from .handlers.settings import router as settings_router
from .handlers.add_expense import router as add_expense_router
from ..core.config import settings
from ..db.database import init_db, close_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(
    token=settings.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()


dp.include_router(handlers_router)
dp.include_router(budget_router)
dp.include_router(settings_router)
dp.include_router(add_expense_router)


async def on_startup():
    logger.info("Initializing database...")
    await init_db()
    logger.info("Bot started!")


async def on_shutdown():
    logger.info("Shutting down...")
    await close_db()
    await bot.session.close()


async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())