import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from ...services.monthly_report import (
    build_summary_data,
    format_summary_text,
    get_all_budgets,
    get_period_dates,
    is_period_active,
)
from ...utils import phrases
from ..keyboards import get_main_menu_keyboard, get_monthly_nav_keyboard
from ..rich_api import edit_rich_message

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
        pd = get_period_dates(next_b)
        prev_label = pd[0].strftime("%b").lower()
    if has_next:
        prev_b = budgets[budget_idx - 1]
        pd = get_period_dates(prev_b)
        next_label = pd[0].strftime("%b").lower()

    return text, has_prev, has_next, prev_label, next_label


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
            bot, callback.message.chat.id, callback.message.message_id, text, kb
        )
    except Exception as e:
        logger.error(f"Monthly report error: {e}", exc_info=True)


@router.callback_query(F.data == "monthly_refresh")
async def monthly_refresh(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    tg_id = callback.from_user.id
    try:
        idx = _get_index(tg_id)
        text, has_prev, has_next, prev_label, next_label = await _build_report_text(tg_id, idx)
        kb = get_monthly_nav_keyboard(has_prev, has_next, prev_label, next_label)
        await edit_rich_message(
            bot, callback.message.chat.id, callback.message.message_id, text, kb
        )
    except Exception as e:
        logger.error(f"Monthly refresh error: {e}", exc_info=True)


@router.callback_query(F.data == "monthly_prev")
async def monthly_prev(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    tg_id = callback.from_user.id
    try:
        idx = _get_index(tg_id)
        if idx >= len(list(await get_all_budgets(tg_id))) - 1:
            return
        _set_index(tg_id, idx + 1)
        text, has_prev, has_next, prev_label, next_label = await _build_report_text(
            tg_id, idx + 1
        )
        kb = get_monthly_nav_keyboard(has_prev, has_next, prev_label, next_label)
        await edit_rich_message(
            bot, callback.message.chat.id, callback.message.message_id, text, kb
        )
    except Exception as e:
        logger.error(f"Monthly nav error: {e}", exc_info=True)


@router.callback_query(F.data == "monthly_next")
async def monthly_next(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    tg_id = callback.from_user.id
    try:
        idx = _get_index(tg_id)
        if idx <= 0:
            return
        _set_index(tg_id, idx - 1)
        text, has_prev, has_next, prev_label, next_label = await _build_report_text(
            tg_id, idx - 1
        )
        kb = get_monthly_nav_keyboard(has_prev, has_next, prev_label, next_label)
        await edit_rich_message(
            bot, callback.message.chat.id, callback.message.message_id, text, kb
        )
    except Exception as e:
        logger.error(f"Monthly nav error: {e}", exc_info=True)
