from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import Bot

from ...services.evening_report import send_evening_teaser
from ...services.morning_report import send_morning_reports

router = Router()


@router.message(Command("test_evening"))
async def cmd_test_evening(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏁 Показать отчет", callback_data="generate_evening_report")],
    ])
    await message.answer(
        text="👁 Псс, день подходит к концу!\n\n"
             "Твой вечерний отчет по тратам уже готов. Если забыл что-то внести "
             "(например, ту самую чистку или аптеку), допиши прямо сейчас обычным сообщением.\n\n"
             "Если всё внесено — жми кнопку ниже, подведем итоги! 📊",
        reply_markup=keyboard,
    )


@router.message(Command("test_teaser"))
async def cmd_test_teaser(message: Message, bot: Bot):
    await message.answer("🚀 Запускаю принудительный тизер...")
    await send_evening_teaser(bot)
    await message.answer("🏁 Тизер отправлен всем пользователям!")


@router.message(Command("test_morning"))
async def cmd_test_morning(message: Message, bot: Bot):
    await send_morning_reports(bot)
