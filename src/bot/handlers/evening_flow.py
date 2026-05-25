import asyncio
import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ...services.evening_report import send_actual_report, _reported_today
from ..keyboards import get_main_menu_keyboard

logger = logging.getLogger(__name__)

router = Router()


@router.callback_query(F.data == "generate_evening_report")
async def handle_evening_report_click(callback: CallbackQuery):
    telegram_id = callback.from_user.id

    try:
        await callback.message.delete()
    except Exception:
        pass

    loading = await callback.message.answer("🧠 Анализирую твои растраты...")

    await asyncio.sleep(1.5)

    await loading.delete()

    success = await send_actual_report(telegram_id, callback.bot)
    if success:
        _reported_today.add(telegram_id)
    else:
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ В главное меню", callback_data="open_menu")
        await callback.message.answer(
            text="❌ Не удалось сформировать отчёт. Возможно, у тебя ещё нет бюджета на этот месяц.\n"
                 "Нажми /start, чтобы настроить!",
            reply_markup=builder.as_markup(),
        )
