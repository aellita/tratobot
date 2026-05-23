from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram import Bot

from ...services.evening_report import send_evening_reports
from ...services.morning_report import send_morning_reports

router = Router()


@router.message(Command("test_evening"))
async def cmd_test_evening(message: Message, bot: Bot):
    await message.answer("🚀 Запускаю принудительный ВЕЧЕРНИЙ отчёт...")
    await send_evening_reports(bot)
    await message.answer("🏁 Вечерний отчёт выполнен!")


@router.message(Command("test_morning"))
async def cmd_test_morning(message: Message, bot: Bot):
    await message.answer("🚀 Запускаю принудительный УТРЕННИЙ отчёт...")
    await send_morning_reports(bot)
    await message.answer("🏁 Утренний отчёт выполнен!")
