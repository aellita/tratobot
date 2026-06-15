import asyncio
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from src.utils import phrases
from src.utils.helpers import get_msk_now

from ...db.database import async_session_maker
from ...db.models.models import Expense
from ...services.budget_service import get_active_budget
from ...services.evening_report import (
    EVENING_KB,
    EveningState,
    _build_container_text,
    get_evening_message,
)
from ...services.expense_service import (
    get_current_period_expenses_sum,
    get_today_daily_limit,
    get_today_expenses_sum,
    parse_expense_text,
)
from ...utils.helpers import safe
from ..keyboards import get_main_menu_keyboard

logger = logging.getLogger(__name__)

router = Router()


@router.message(EveningState.filling)
async def handle_evening_expense(message: Message, state: FSMContext):
    user_id = message.from_user.id

    await message.delete()

    if not message.text or not message.text.strip():
        temp = await message.answer(phrases.ERR_EMPTY_EXPENSE)
        await asyncio.sleep(3)
        await temp.delete()
        return

    parsed = parse_expense_text(message.text)
    if not parsed:
        temp = await message.answer(phrases.ERR_PARSE_EXPENSE)
        await asyncio.sleep(3)
        await temp.delete()
        return

    amount, description = parsed

    async with async_session_maker() as session:
        expense = Expense(
            telegram_id=user_id,
            amount=amount,
            description=description,
            date=get_msk_now(),
        )
        session.add(expense)
        await session.commit()

    data = await state.get_data()
    container_id = data.get("container_id")
    session_expenses = data.get("session_expenses", [])

    line = (
        phrases.EVENING_LINE_DESC.format(amount=f"{amount:,.0f}", desc=safe(description))
        if description
        else phrases.EVENING_LINE.format(amount=f"{amount:,.0f}")
    )
    session_expenses.append(line)
    await state.update_data(session_expenses=session_expenses)

    try:
        await message.bot.edit_message_text(
            chat_id=user_id,
            message_id=container_id,
            text=_build_container_text(session_expenses),
            reply_markup=EVENING_KB,
        )
    except Exception:
        pass


@router.callback_query(F.data == "show_final_evening_report", EveningState.filling)
async def finalize_evening_report(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    user_id = callback.from_user.id

    limit = await get_today_daily_limit(user_id)
    spent = await get_today_expenses_sum(user_id)
    budget = await get_active_budget(user_id)

    if budget:
        days_left = budget.days_remaining
        if budget.free_money > 0:
            total_available = budget.free_money
        else:
            total_available = (
                budget.total_income - budget.mandatory_payments - budget.black_day_fund
            )
        period_spent = await get_current_period_expenses_sum(user_id)
        available_cash = max(total_available - period_spent, 0)
    else:
        days_left = 1
        available_cash = 0

    if limit <= 0:
        await callback.message.answer(
            phrases.ERR_REPORT_FAILED,
            reply_markup=get_main_menu_keyboard(user_id),
        )
        await state.clear()
        return

    text = get_evening_message(
        limit=limit,
        spent=spent,
        available_cash=available_cash,
        days_left=days_left,
    )

    main_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=phrases.BTN_BACK_MAIN, callback_data="open_menu")],
        ]
    )
    await callback.message.answer(text, reply_markup=main_kb)

    await state.clear()
