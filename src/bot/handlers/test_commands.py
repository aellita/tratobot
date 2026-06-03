from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiogram import Bot

from ...services.evening_report import send_evening_teaser, EveningState, EVENING_KB, INITIAL_TEXT
from ...services.morning_report import send_morning_reports

router = Router()


@router.message(Command("test_evening"))
async def cmd_test_evening(message: Message, state: FSMContext):
    msg = await message.answer(INITIAL_TEXT, reply_markup=EVENING_KB)
    await state.set_state(EveningState.filling)
    await state.update_data(container_id=msg.message_id, session_expenses=[])
    await message.delete()


@router.message(Command("test_teaser"))
async def cmd_test_teaser(message: Message, bot: Bot, state: FSMContext):
    await message.answer("🚀 Запускаю принудительный тизер...")
    await send_evening_teaser(bot, state.storage)
    await message.answer("🏁 Тизер отправлен всем пользователям!")


@router.message(Command("test_morning"))
async def cmd_test_morning(message: Message, bot: Bot):
    await send_morning_reports(bot)
