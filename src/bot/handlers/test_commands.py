from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ...services.evening_report import EVENING_KB, INITIAL_TEXT, EveningState, send_evening_teaser
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


@router.message(Command("test_monthly_summary"))
async def cmd_test_monthly_summary(message: Message, bot: Bot):
    from datetime import timedelta

    from sqlalchemy import select

    from ...db.database import async_session_maker
    from ...db.models.models import Budget
    from ...services.monthly_report import (
        build_summary_data,
        format_summary_text,
        get_average_expenses,
        get_period_dates,
    )
    from ...utils import phrases
    from ...utils.helpers import get_msk_now
    from ..keyboards import get_rollover_keyboard
    from ..rich_api import send_rich_message

    tg_id = message.from_user.id

    today = get_msk_now().date()
    async with async_session_maker() as session:
        result = await session.execute(
            select(Budget).where(Budget.telegram_id == tg_id)
        )
        budgets = list(result.scalars().all())

    if not budgets:
        await message.answer("❌ У тебя нет ни одного бюджета.")
        return

    budget = None
    for b in budgets:
        _, pe = get_period_dates(b)
        if today == pe.date() + timedelta(days=1):
            budget = b
            break

    if not budget:
        budget = budgets[0]

    await message.answer("📊 Генерирую Monthly Summary...")

    data = await build_summary_data(tg_id, budget)
    msg = format_summary_text(data)
    await send_rich_message(bot, tg_id, msg)

    avg = await get_average_expenses(tg_id)
    offer = phrases.ROLLOVER_OFFER.format(
        old_date=budget.period_start_day or 1,
        avg=int(avg) if avg > 0 else 0,
        old_income=int(budget.total_income),
    )
    await bot.send_message(tg_id, offer, reply_markup=get_rollover_keyboard(budget.id))
