from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        text=f"Привет! Я бот 'Завтра на диете'.\n\n"
             "Давай наведём порядок в твоих финансах!\n\n"
             "Напиши /help чтобы увидеть доступные команды."
    )


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