from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        text="📋 <b>Доступные команды:</b>\n\n"
             "/start — Начать работу\n"
             "/budget — Установить бюджет\n"
             "/add — Добавить трату\n"
             "/status — Показать статус\n"
             "/categories — Категории трат\n"
             "/settings — Настройки"
    )


@router.message(Command("status"))
async def cmd_status(message: Message):
    await message.answer(text="Пока нет данных. Запусти /start для настройки!")