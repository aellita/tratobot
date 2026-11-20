import asyncio
import json
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from ...services.budget_service import get_base_daily_limit
from ...services.monthly_chart import (
    CHART_WIDGET_HTML,
    MonthlyCardInput,
    build_chart_data,
    build_chart_state,
    render_monthly_card_png,
)
from ...services.monthly_report import (
    build_summary_data,
    format_summary_text,
    get_all_budgets,
    get_period_dates,
    is_period_active,
)
from ...utils import phrases
from ...utils.helpers import get_msk_now
from ..keyboards import get_main_menu_keyboard, get_monthly_nav_keyboard
from ..rich_api import edit_rich_message, send_widget_or_fallback

logger = logging.getLogger(__name__)

router = Router()

_user_index: dict[int, int] = {}


def _set_index(telegram_id: int, idx: int):
    _user_index[telegram_id] = idx


def _get_index(telegram_id: int) -> int:
    return _user_index.get(telegram_id, 0)


async def _build_report_text(telegram_id: int, budget_idx: int) -> tuple[str, bool, bool, str, str]:
    budgets = await get_all_budgets(telegram_id)
    if not budgets or budget_idx < 0 or budget_idx >= len(budgets):
        return f"<p>{phrases.MONTHLY_EMPTY}</p>", False, False, "", ""

    budget = budgets[budget_idx]
    data = await build_summary_data(telegram_id, budget)

    if data["total_spent"] == 0 and not data["active"]:
        return f"<p>{phrases.MONTHLY_EMPTY}</p>", False, False, "", ""

    text = format_summary_text(data)

    has_prev = budget_idx < len(budgets) - 1
    has_next = budget_idx > 0
    prev_label = ""
    next_label = ""
    if has_prev:
        next_b = budgets[budget_idx + 1]
        ps, pe = get_period_dates(next_b)
        prev_label = f"{ps.strftime('%d.%m')}–{pe.strftime('%d.%m')}"
    if has_next:
        prev_b = budgets[budget_idx - 1]
        ps, pe = get_period_dates(prev_b)
        next_label = f"{ps.strftime('%d.%m')}–{pe.strftime('%d.%m')}"

    return text, has_prev, has_next, prev_label, next_label


async def _build_chart_input(
    telegram_id: int,
    budget,
    passed_days: int,
    expenses: list,
    prev_expenses: list | None,
    prev_budget,
    current_income: float,
    prev_income: float,
) -> MonthlyCardInput:
    """Prepare MonthlyCardInput for PNG rendering."""
    period_start, period_end = get_period_dates(budget)
    prev_income = 0.0

    if prev_budget:
        prev_income = float(prev_budget.total_income + prev_budget.added_income)

    current_income = float(budget.total_income + budget.added_income)

    # Get chart data for daily_spent
    chart_data = await build_chart_data(telegram_id, budget)
    daily_spent = [round(d["spent"], 2) for d in chart_data]

    return MonthlyCardInput(
        period_start=period_start,
        period_end=period_end,
        period_start_day=budget.period_start_day or 1,
        daily_spent=daily_spent[:passed_days],
        daily_limit=float(get_base_daily_limit(budget)),
        total_spent=sum(daily_spent[:passed_days]),
        expenses=expenses,
        expenses_count=len(expenses),
        prev_expenses=None,  # prev_expenses handled in render
        prev_period_start=prev_budget.period_start_day and period_start if prev_budget else None,
        current_income=current_income,
        prev_income=prev_income,
    )


async def _send_monthly_chart(
    bot: Bot,
    telegram_id: int,
    chat_id: int,
    budget,
    passed_days: int,
    expenses: list,
    prev_budget,
    current_income: float,
    prev_income: float,
):
    """Send or update monthly chart (widget → PNG fallback)."""
    from ...services.monthly_chart import (
        build_chart_data,
    )

    input_data = await _build_chart_input(
        telegram_id, budget, passed_days, [], None, None,
        float(budget.total_income + budget.added_income),
        float(prev_budget.total_income + prev_budget.added_income) if prev_budget else 0.0,
    )

    # Render PNG
    png_bytes = await asyncio.to_thread(render_monthly_card_png, input_data)

    # Widget HTML + state
    chart_data = await build_chart_data(telegram_id, budget)
    state = build_chart_state(telegram_id, budget, chart_data)
    state_json = json.dumps(state, separators=(",", ":"))

    # Try widget → fallback to PNG
    method, msg = await send_widget_or_fallback(
        bot, chat_id, CHART_WIDGET_HTML, state_json, png_bytes
    )

    if method == "widget":
        from ..widget_cache import set_widget_msg
        set_widget_msg(telegram_id, chat_id, msg.message_id)
    else:
        from ..widget_cache import set_photo_msg
        set_photo_msg(telegram_id, chat_id, msg.message_id)


@router.callback_query(F.data == "menu_monthly_report")
async def cmd_monthly_report(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    await state.clear()
    tg_id = callback.from_user.id
    try:
        budgets = await get_all_budgets(tg_id)
        if not budgets:
            await edit_rich_message(
                bot,
                callback.message.chat.id,
                callback.message.message_id,
                f"<p>{phrases.ERR_NO_BUDGET}</p>",
                await get_main_menu_keyboard(tg_id),
            )
            return

        active_idx = 0
        for i, b in enumerate(budgets):
            if is_period_active(b):
                active_idx = i
                break

        _set_index(tg_id, active_idx)
        text, has_prev, has_next, prev_label, next_label = await _build_report_text(
            tg_id, active_idx
        )
        kb = get_monthly_nav_keyboard(has_prev, has_next, prev_label, next_label)
        await edit_rich_message(
            bot,
            callback.message.chat.id,
            callback.message.message_id,
            text,
            kb,
        )

        # Clear both caches so fresh content appears at bottom
        from ..widget_cache import clear_photo_msg, clear_widget_msg
        clear_widget_msg(tg_id, callback.message.chat.id)
        clear_photo_msg(tg_id, callback.message.chat.id)

        budget = budgets[active_idx]
        period_start, period_end = get_period_dates(budget)
        today = get_msk_now().date()
        passed_days = min(30, (today - period_start).days + 1)

        # Get previous budget data
        prev_budget = budgets[active_idx + 1] if active_idx + 1 < len(budgets) else None
        current_income = float(budget.total_income + budget.added_income)
        prev_income = (
            float(prev_budget.total_income + prev_budget.added_income)
            if prev_budget else 0.0
        )

        # Send chart with fallback
        await _send_monthly_chart(
            bot, tg_id, callback.message.chat.id, budget,
            passed_days, [], prev_budget,
            current_income, prev_income
        )

    except Exception as e:
        logger.error(f"Monthly report error: {e}", exc_info=True)


@router.callback_query(F.data == "monthly_refresh")
async def monthly_refresh(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    tg_id = callback.from_user.id
    try:
        idx = _get_index(tg_id)
        budgets = await get_all_budgets(tg_id)
        if not budgets or idx >= len(budgets):
            return
        text, has_prev, has_next, prev_label, next_label = await _build_report_text(tg_id, idx)
        kb = get_monthly_nav_keyboard(has_prev, has_next, prev_label, next_label)
        await edit_rich_message(
            bot, callback.message.chat.id, callback.message.message_id, text, kb
        )

        budget = budgets[idx]
        period_start, period_end = get_period_dates(budget)
        today = get_msk_now().date()
        passed_days = min(30, (today - period_start).days + 1)

        prev_budget = budgets[idx + 1] if idx + 1 < len(budgets) else None
        current_income = float(budget.total_income + budget.added_income)
        prev_income = (
            float(prev_budget.total_income + prev_budget.added_income)
            if prev_budget else 0.0
        )

        await _send_monthly_chart(
            bot, tg_id, callback.message.chat.id, budget,
            passed_days, [], prev_budget,
            current_income, prev_income
        )

    except Exception as e:
        logger.error(f"Monthly refresh error: {e}", exc_info=True)


@router.callback_query(F.data == "monthly_prev")
async def monthly_prev(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    tg_id = callback.from_user.id
    try:
        idx = _get_index(tg_id)
        budgets = await get_all_budgets(tg_id)
        if idx >= len(budgets) - 1:
            return
        new_idx = idx + 1
        _set_index(tg_id, new_idx)
        text, has_prev, has_next, prev_label, next_label = await _build_report_text(tg_id, new_idx)
        kb = get_monthly_nav_keyboard(has_prev, has_next, prev_label, next_label)
        await edit_rich_message(
            bot, callback.message.chat.id, callback.message.message_id, text, kb
        )

        budget = budgets[new_idx]
        period_start, period_end = get_period_dates(budget)
        passed_days = min(30, (get_msk_now().date() - period_start).days + 1)

        prev_budget = budgets[new_idx + 1] if new_idx + 1 < len(budgets) else None
        current_income = float(budget.total_income + budget.added_income)
        prev_income = (
            float(prev_budget.total_income + prev_budget.added_income)
            if prev_budget else 0.0
        )

        await _send_monthly_chart(
            bot, tg_id, callback.message.chat.id, budget,
            passed_days, [], prev_budget, current_income, prev_income
        )

    except Exception as e:
        logger.error(f"Monthly nav error: {e}", exc_info=True)


@router.callback_query(F.data == "monthly_next")
async def monthly_next(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    tg_id = callback.from_user.id
    try:
        idx = _get_index(tg_id)
        budgets = await get_all_budgets(tg_id)
        if idx <= 0:
            return
        new_idx = idx - 1
        _set_index(tg_id, new_idx)
        text, has_prev, has_next, prev_label, next_label = await _build_report_text(tg_id, new_idx)
        kb = get_monthly_nav_keyboard(has_prev, has_next, prev_label, next_label)
        await edit_rich_message(
            bot, callback.message.chat.id, callback.message.message_id, text, kb
        )

        budget = budgets[new_idx]
        period_start, period_end = get_period_dates(budget)
        passed_days = min(30, (get_msk_now().date() - period_start).days + 1)

        prev_budget = budgets[new_idx + 1] if new_idx + 1 < len(budgets) else None
        current_income = float(budget.total_income + budget.added_income)
        prev_income = (
            float(prev_budget.total_income + prev_budget.added_income)
            if prev_budget else 0.0
        )

        await _send_monthly_chart(
            bot, tg_id, callback.message.chat.id, budget,
            passed_days, [], prev_budget, current_income, prev_income
        )

    except Exception as e:
        logger.error(f"Monthly nav error: {e}", exc_info=True)
