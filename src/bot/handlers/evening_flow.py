import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from src.core.config import settings
from src.utils import phrases
from src.utils.helpers import get_msk_now

from ...db.database import async_session_maker
from ...db.models.models import Expense
from ...services.budget_service import get_active_budget
from ...services.categorization import detect_category_db, get_category_display
from ...services.evening_report import (
    EVENING_KB,
    EveningState,
    _build_container_text,
    get_evening_message,
)
from ...services.expense_service import (
    get_current_period_expenses_sum,
    get_today_expenses_sum,
    parse_multi_expense_text,
)
from ...utils.helpers import safe
from ..keyboards import get_main_menu_keyboard
from ._shared import handle_invalid_input

logger = logging.getLogger(__name__)

router = Router()


@router.message(EveningState.filling)
async def handle_evening_expense(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if not message.text or not message.text.strip():
        await message.answer(phrases.ERR_EMPTY_EXPENSE)
        return

    result = parse_multi_expense_text(message.text)
    if not result.reports:
        return

    if not result.is_fully_valid:
        invalid = next((r for r in result.reports if not r.is_valid), None)
        if invalid and invalid.error_type == "MATH_ERROR":
            await handle_invalid_input(
                message,
                state,
                phrases.ERR_MATH_ERROR.format(detail=invalid.error_detail or invalid.raw_text),
            )
        else:
            await handle_invalid_input(
                message,
                state,
                phrases.ERR_PARSE_EXPENSE,
            )
        return

    response_parts = []
    container_lines = []

    for report in result.reports:
        amount = report.amount
        description = report.description

        cat, _ = await detect_category_db(description, user_id, amount)
        cat_id = cat.id if cat else None
        emoji = ""
        if cat:
            emoji_char, _ = get_category_display(cat.name)
            emoji = f"{emoji_char} "

        async with async_session_maker() as session:
            expense = Expense(
                telegram_id=user_id,
                amount=amount,
                description=description,
                category_id=cat_id,
                date=get_msk_now(),
            )
            session.add(expense)
            await session.commit()

        saved_line = phrases.EVENING_SAVED.format(
            emoji=emoji, amount=f"{amount:,.0f}", desc=safe(description)
        )
        if report.was_corrected:
            saved_line = (
                saved_line
                + "\n"
                + phrases.ERR_MATH_CORRECTED.format(hint=report.correction_hint or "")
            )
        response_parts.append(saved_line)

        line = (
            phrases.EVENING_LINE_DESC.format(amount=f"{amount:,.0f}", desc=safe(description))
            if description
            else phrases.EVENING_LINE.format(amount=f"{amount:,.0f}")
        )
        container_lines.append(line)

    await message.answer("\n".join(response_parts))

    data = await state.get_data()
    container_id = data.get("container_id")
    session_expenses = data.get("session_expenses", [])
    session_expenses.extend(container_lines)
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


@router.callback_query(F.data == "show_final_evening_report")
async def finalize_evening_report(callback: CallbackQuery, state: FSMContext):
    try:
        current_state = await state.get_state()
        is_filling = current_state == EveningState.filling.state
        # stale: кнопка старше текущего логического дня — молча убираем клавиатуру без нового отчёта
        try:
            msg_date = callback.message.date.date() if callback.message.date else None
            today = get_msk_now().date()
            if msg_date and msg_date != today:
                logger.info(f"Evening stale button {msg_date} != {today}, silent close")
                try:
                    await callback.message.edit_reply_markup(reply_markup=None)
                except Exception:
                    pass
                await state.clear()
                await callback.answer()
                return
        except Exception:
            pass
        if not is_filling:
            logger.info(f"Evening report callback without filling state {current_state}, fallback render")
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

        user_id = callback.from_user.id

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
            limit = max(available_cash / max(days_left, 1), 0)
        else:
            days_left = 1
            available_cash = 0
            limit = 0

        if limit <= 0:
            await callback.message.answer(
                phrases.ERR_REPORT_FAILED,
                reply_markup=await get_main_menu_keyboard(user_id),
            )
            await state.clear()
            await callback.answer()
            return

        text = get_evening_message(
            limit=limit,
            spent=spent,
            available_cash=available_cash,
            days_left=days_left,
        )

        kb = None
        if not settings.EXPENSE_SIMPLE_CHECK:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=phrases.BTN_BACK_MAIN, callback_data="open_menu")],
                ]
            )
        await callback.message.answer(text, reply_markup=kb)

        await state.clear()
        await callback.answer()
    except Exception as e:
        logger.error(f"Evening report finalize failed: {e}", exc_info=True)
        try:
            await callback.message.answer(
                phrases.ERR_REPORT_FAILED,
                reply_markup=await get_main_menu_keyboard(callback.from_user.id),
            )
            await state.clear()
        except Exception:
            pass
        try:
            await callback.answer()
        except Exception:
            pass
