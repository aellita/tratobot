import logging
import random
import re
from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from ...core.config import settings
from ...db.database import async_session_maker
from ...db.models.models import (
    Budget,
    Category,
    Expense,
    User,
    UserSettings,
    Wishlist,
)
from ...services.budget_service import (
    apply_reconciliation,
    delete_current_budget,
    get_active_budget,
    reconcile_budget_with_reality,
    save_budget,
    update_budget_field,
)
from ...services.categorization import (
    GREETINGS,
    _dump_keywords,
    add_keyword_to_category,
    clean_and_normalize,
    detect_category_db,
    get_category_display,
    get_user_categories,
    seed_user_categories,
)
from ...services.expense_service import (
    ExpenseParseReport,
    get_today_expenses_grouped,
    get_today_expenses_sum,
    parse_multi_expense_text,
)
from ...services.user_service import get_or_create_user
from ...utils import phrases
from ...utils.helpers import build_category_name, get_msk_now, get_user_now, parse_amount, safe
from ..callbacks import RolloverCb
from ..keyboards import (
    get_advanced_planning_keyboard,
    get_cancel_keyboard,
    get_change_budget_choice_keyboard,
    get_duplicate_keyboard,
    get_keep_date_keyboard,
    get_keep_income_keyboard,
    get_main_menu_keyboard,
    get_main_reply_keyboard,
    get_onboarding_keyboard,
    get_period_start_keyboard,
    get_rounding_mode_keyboard,
    get_settings_keyboard,
    get_start_choice_keyboard,
    get_stats_keyboard,
)
from ..middleware import dup_middleware
from ._shared import handle_invalid_input

REPLY_MENU_COMMANDS = frozenset(
    {
        phrases.BTN_ADD_EXPENSE,
        phrases.BTN_DAILY_LIMIT,
        phrases.BTN_STATS,
        phrases.BTN_SETTINGS,
        phrases.BTN_HELP,
    }
)

router = Router()

_from_advanced_planning: set[int] = set()


def _plural_days(n: int) -> str:
    n = abs(n) % 100
    n1 = n % 10
    if 11 <= n <= 14:
        return "дней"
    if n1 == 1:
        return "день"
    if 2 <= n1 <= 4:
        return "дня"
    return "дней"


async def _handle_recovery_budget_change(telegram_id: int, message: Message):
    if not settings.RECOVERY_ENABLED:
        return
    try:
        from ...services.budget_service import get_active_budget as _get_budget
        from ...services.recovery_service import (
            check_success,
            complete_recovery,
            get_active_recovery,
            recalculate_days,
            update_recovery_days,
        )

        budget = await _get_budget(telegram_id)
        if not budget:
            return
        active = await get_active_recovery(telegram_id)
        if not active:
            return
        from ...services.budget_service import (
            get_daily_pred,
            get_money_for_life,
            get_period_spent,
        )

        spent_period = await get_period_spent(telegram_id, budget)
        money_for_life = get_money_for_life(budget, spent_period)
        days_left = budget.days_remaining
        dl_pred = get_daily_pred(money_for_life, days_left)
        if check_success(dl_pred, active.baseline):
            await complete_recovery(telegram_id, "budget_update")
            await message.answer(text=phrases.RECOVERY_BUDGET_DONE)
            return
        deficit = max(active.baseline * days_left - money_for_life, 0)
        new_days = recalculate_days(deficit, active.baseline, active.target)
        if new_days is None:
            await complete_recovery(telegram_id, "budget_update")
            await message.answer(text=phrases.RECOVERY_BUDGET_DONE)
            return
        if new_days + 7 > days_left:
            await complete_recovery(telegram_id, "period_end")
            await message.answer(text=phrases.RECOVERY_PERIOD_END)
            return
        if new_days != active.total_days:
            old = active.total_days
            await update_recovery_days(telegram_id, new_days)
            if new_days < old:
                await message.answer(
                    text=phrases.RECOVERY_BUDGET_SHORTENED.format(
                        old=old, new=new_days, word=_plural_days(new_days)
                    )
                )
    except Exception as e:
        logging.error(f"Recovery budget hook failed {telegram_id}: {e}", exc_info=True)


class BudgetSetup(StatesGroup):
    waiting_for_income = State()
    waiting_for_period_start = State()
    waiting_for_mandatory = State()
    waiting_for_black_day = State()
    waiting_for_wishlist_name = State()
    waiting_for_rounding_mode = State()


class NewPeriodSetup(StatesGroup):
    waiting_for_income = State()
    waiting_for_period_start = State()


class EditBudget(StatesGroup):
    waiting_for_add_income = State()
    waiting_for_period_start = State()
    waiting_for_mandatory = State()
    waiting_for_black_day = State()
    waiting_for_wishlist = State()
    waiting_for_recalc_balance = State()


class AddExpense(StatesGroup):
    waiting_for_amount = State()


class CustomCategory(StatesGroup):
    waiting_for_name = State()


async def get_user_or_none(telegram_id: int) -> User | None:
    async with async_session_maker() as session:
        return await session.get(User, telegram_id)


async def get_budget_or_none(telegram_id: int) -> Budget | None:
    from ...services.budget_service import get_active_budget

    return await get_active_budget(telegram_id)


def _build_expense_check_kb(
    first_id: int | None, line_count: int, corrected_ids: list[int] | None = None
) -> InlineKeyboardMarkup | None:
    fix_id = (corrected_ids or [None])[0]
    if not settings.EXPENSE_SIMPLE_CHECK:
        if line_count == 1:
            buttons = []
            if fix_id is not None:
                buttons.append(
                    [
                        InlineKeyboardButton(
                            text=phrases.BTN_FIX_AMOUNT, callback_data=f"exp_edit:{fix_id}"
                        )
                    ]
                )
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=phrases.BTN_CHANGE_CATEGORY,
                        callback_data=f"change_cat:{first_id}",
                    )
                ]
            )
            buttons.append(
                [InlineKeyboardButton(text=phrases.BTN_BACK_MAIN, callback_data="menu_back")]
            )
            return InlineKeyboardMarkup(inline_keyboard=buttons)
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=phrases.BTN_BACK_MAIN, callback_data="menu_back")],
            ]
        )
    if line_count == 1 and first_id:
        buttons = []
        if fix_id is not None:
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=phrases.BTN_FIX_AMOUNT, callback_data=f"exp_edit:{fix_id}"
                    )
                ]
            )
        buttons.append(
            [
                InlineKeyboardButton(
                    text=phrases.BTN_CHANGE_CATEGORY,
                    callback_data=f"change_cat:{first_id}",
                )
            ]
        )
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    return None


# ============ MENU HANDLERS ============


@router.callback_query(F.data == "menu_back")
async def menu_back(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if settings.EXPENSE_SIMPLE_CHECK:
        return
    await state.clear()
    await callback.message.edit_text(
        text=phrases.BACK_NAV,
        reply_markup=await get_main_menu_keyboard(callback.from_user.id),
    )


@router.callback_query(F.data == "menu_stats")
async def menu_stats(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.edit_text(
        text=phrases.BTN_STATS,
        reply_markup=get_stats_keyboard(),
    )


@router.callback_query(F.data == "menu_help")
async def menu_help(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        text=phrases.HELP_TEXT,
        reply_markup=await get_main_menu_keyboard(callback.from_user.id),
    )


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    telegram_id = message.from_user.id

    user = await get_user_or_none(telegram_id)

    if not user:
        await get_or_create_user(
            telegram_id=telegram_id,
            first_name=message.from_user.first_name,
            username=message.from_user.username,
        )
        await seed_user_categories(telegram_id)
        greeting = random.choice(GREETINGS)
        await message.answer(text=greeting)

        await message.answer(text=phrases.ONBOARDING_START, reply_markup=get_cancel_keyboard())
        await state.set_state(BudgetSetup.waiting_for_income)
    else:
        await message.answer(
            text=phrases.WELCOME_BACK,
            reply_markup=get_start_choice_keyboard(),
        )
        if settings.EXPENSE_SIMPLE_CHECK:
            await message.answer(
                text=phrases.WELCOME_MENU,
                reply_markup=get_main_reply_keyboard(),
            )


@router.callback_query(F.data == "open_menu")
async def open_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if settings.EXPENSE_SIMPLE_CHECK:
        return
    await state.clear()
    await callback.message.edit_text(
        text=phrases.BACK_NAV,
        reply_markup=await get_main_menu_keyboard(callback.from_user.id),
    )


@router.callback_query(F.data == "report_back")
async def report_back(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if settings.EXPENSE_SIMPLE_CHECK:
        return
    await state.clear()
    await callback.message.answer(
        text=phrases.BACK_NAV,
        reply_markup=await get_main_menu_keyboard(callback.from_user.id),
    )


@router.callback_query(F.data == "reset_budget")
async def reset_budget(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()

    await get_or_create_user(
        telegram_id=callback.from_user.id,
        first_name=callback.from_user.first_name,
        username=callback.from_user.username,
    )
    await seed_user_categories(callback.from_user.id)

    await delete_current_budget(callback.from_user.id)

    greeting = random.choice(GREETINGS)
    await callback.message.edit_text(text=greeting)

    await callback.message.answer(
        text=phrases.ONBOARDING_RESTART, reply_markup=get_onboarding_keyboard()
    )
    await state.set_state(BudgetSetup.waiting_for_income)


@router.callback_query(RolloverCb.filter(F.action == "keep"))
async def rollover_keep_budget(
    callback: CallbackQuery,
    callback_data: RolloverCb,
    state: FSMContext,
):
    await callback.answer()
    await state.clear()

    async with async_session_maker() as session:
        old = await session.get(Budget, callback_data.budget_id)

    if not old:
        await callback.answer(phrases.ERR_ROLLOVER_NOT_FOUND, show_alert=True)
        return

    tg_id = callback.from_user.id
    month = get_msk_now().strftime("%Y-%m")

    old_mandatory = old.mandatory_payments
    old_wishlist_name = old.wishlist_name
    old_wishlist_target = old.wishlist_target

    await save_budget(
        telegram_id=tg_id,
        month=month,
        free_money=0,
        income=old.total_income,
        mandatory=old_mandatory,
        black_day=0,
        wishlist_name=old_wishlist_name or phrases.DEFAULT_WISHLIST_NAME,
        wishlist_price=old_wishlist_target,
        period_start_day=old.period_start_day or 1,
    )
    if settings.RECOVERY_ENABLED:
        try:
            from ...services.recovery_service import expire_active_recoveries_for_budget

            await expire_active_recoveries_for_budget(old.id)
        except Exception:
            pass

    from ..middleware import _last_keyboard

    _last_keyboard.pop(tg_id, None)

    budget = await get_active_budget(tg_id)
    dl = int(budget.daily_limit) if budget else 0

    carried_parts = []
    if old_mandatory > 0:
        carried_parts.append(
            phrases.ROLLOVER_CARRIED_MANDATORY.format(amount=f"{int(old_mandatory):,}")
        )
    if old_wishlist_target > 0 and old_wishlist_name:
        carried_parts.append(
            phrases.ROLLOVER_CARRIED_WISHLIST.format(
                name=safe(old_wishlist_name), amount=f"{int(old_wishlist_target):,}"
            )
        )

    if carried_parts:
        text = phrases.ROLLOVER_WITH_DETAILS.format(parts="\n".join(carried_parts), limit=dl)
    else:
        text = phrases.ROLLOVER_CONFIRMED.format(daily_limit=dl)

    await callback.message.edit_text(text=text)


@router.callback_query(RolloverCb.filter(F.action == "edit"))
async def rollover_edit_budget(
    callback: CallbackQuery,
    callback_data: RolloverCb,
    state: FSMContext,
):
    await callback.answer()
    await state.clear()

    async with async_session_maker() as session:
        old = await session.get(Budget, callback_data.budget_id)

    if not old:
        await callback.answer(phrases.ERR_ROLLOVER_NOT_FOUND, show_alert=True)
        return

    old_income = old.total_income
    old_date = old.period_start_day or 1

    await state.update_data(old_income=old_income, old_date=old_date, income=old_income)

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    text = phrases.ROLLOVER_ASK_INCOME.format(amount=f"{int(old_income):,}")
    await callback.message.answer(text=text, reply_markup=get_keep_income_keyboard(old_income))
    await state.set_state(NewPeriodSetup.waiting_for_income)


@router.callback_query(F.data == "menu_status")
async def menu_status(callback: CallbackQuery):
    await callback.answer()
    text, kb = await _build_status(callback.from_user.id)
    await callback.message.edit_text(text=text, reply_markup=kb)


async def _build_status(telegram_id: int) -> tuple[str, InlineKeyboardMarkup]:
    tg_id = telegram_id

    budget = await get_budget_or_none(tg_id)
    if not budget:
        return phrases.NO_BUDGET, await get_main_menu_keyboard(tg_id)

    async with async_session_maker() as session:
        today_start = get_msk_now().replace(hour=0, minute=0, second=0, microsecond=0)
        result = await session.execute(
            select(func.sum(Expense.amount)).where(
                Expense.telegram_id == tg_id,
                Expense.is_deleted == False,
                Expense.date >= today_start,
            )
        )
        spent_today = result.scalar() or 0

        from ...services.monthly_report import get_period_dates

        period_start, period_end = get_period_dates(budget)
        next_day = period_end + timedelta(days=1)

        result = await session.execute(
            select(func.sum(Expense.amount)).where(
                Expense.telegram_id == tg_id,
                Expense.is_deleted == False,
                Expense.date >= period_start,
                Expense.date < next_day,
            )
        )
        spent_period = result.scalar() or 0

    days_left = budget.days_remaining
    dl_base = budget.daily_limit

    from ...services.budget_service import get_daily_pred, get_money_for_life

    money_for_life = get_money_for_life(budget, spent_period)
    dl_pred = get_daily_pred(money_for_life, days_left)
    pct_pred = dl_pred / max(dl_base, 1) * 100 if dl_base > 0 else 0

    remaining_today = max(dl_pred - spent_today, 0)
    remaining_period = money_for_life
    period_end_day = budget.period_start_day or 1
    period_end_str = f"{period_end_day}{phrases.PERIOD_DAY_SUFFIX}"

    end_of_period = days_left <= 3

    if end_of_period and money_for_life <= 0:
        zone_emoji = "🔴"
        zone_label = phrases.STATUS_ZONE_ATAS
    elif end_of_period:
        zone_emoji = "🟢"
        zone_label = phrases.STATUS_ZONE_FINISH
    elif pct_pred > 80:
        zone_emoji = "🟢"
        zone_label = phrases.STATUS_ZONE_IN_LIMIT
    elif pct_pred >= 51:
        zone_emoji = "🔵"
        zone_label = phrases.STATUS_ZONE_CAN_MORE
    elif pct_pred >= 26:
        zone_emoji = "🟡"
        zone_label = phrases.STATUS_ZONE_ON_EDGE
    else:
        zone_emoji = "🔴"
        zone_label = phrases.STATUS_ZONE_CRITICAL

    if remaining_today > 0:
        today_line = phrases.STATUS_REMAINING_FREE.format(amount=f"{int(remaining_today):,}")
    else:
        today_line = phrases.STATUS_REMAINING_ZERO

    spent_line = phrases.STATUS_SPENT.format(amount=f"{int(spent_today):,}")
    if spent_today > dl_pred:
        spent_line += " ⚠️"

    expense_lines = await get_today_expenses_grouped(tg_id)
    expenses_block = ""
    if expense_lines:
        expenses_block = "\n<blockquote>" + "\n".join(expense_lines) + "</blockquote>"

    reserve_parts: list[str] = []
    if budget.mandatory_payments:
        reserve_parts.append(
            phrases.STATUS_RESERVE_MANDATORY.format(amount=f"{int(budget.mandatory_payments):,}")
        )

    reserves_block = ""
    if reserve_parts:
        reserves_block = f"\n\n<b>{phrases.STATUS_RESERVES_HEADER}</b>\n" + " · ".join(
            reserve_parts
        )

    # fetch recovery early for UI priority (Zone footer hidden when offer/active)
    _recovery_active = None
    _recovery_offer = False
    if settings.RECOVERY_ENABLED and budget:
        try:
            from ...services.budget_service import resolve_frozen_baseline as _resolve
            from ...services.recovery_service import (
                calculate_recovery_options as _calc_opts,
            )
            from ...services.recovery_service import (
                get_active_recovery as _gar,
            )
            from ...services.recovery_service import (
                get_offer_state as _gos,
            )
            from ...services.recovery_service import (
                should_repeat_offer as _sro,
            )

            _recovery_active = await _gar(tg_id)
            if _recovery_active is None:
                _b_val_tmp = await _resolve(budget)
                _opts_tmp = _calc_opts(_b_val_tmp, money_for_life, days_left)
                if _opts_tmp:
                    _offer_state_tmp = await _gos(tg_id)
                    _should = True
                    if (
                        _offer_state_tmp
                        and _offer_state_tmp.dismissed
                        and _offer_state_tmp.last_offer_at
                    ):
                        _days_since = (
                            get_user_now().date() - _offer_state_tmp.last_offer_at.date()
                        ).days
                        _cur_def = max(_b_val_tmp * days_left - money_for_life, 0)
                        if not _sro(
                            _offer_state_tmp.last_offer_deficit, _cur_def, _b_val_tmp, _days_since
                        ):
                            _should = False
                    if _should:
                        _recovery_offer = True
        except Exception:
            pass

    # today line: if active, use target
    _remaining_period_line = phrases.STATUS_REMAINING_PERIOD.format(
        amount=f"{int(remaining_period):,}", limit=f"{int(dl_pred):,}"
    )
    if _recovery_active is not None:
        _target_int = int(_recovery_active.target)
        _rem_target = max(_target_int - int(spent_today), 0)
        if _rem_target > 0:
            today_line = phrases.STATUS_REMAINING_FREE.format(amount=f"{_rem_target:,}")
        else:
            today_line = phrases.STATUS_REMAINING_ZERO
        _cur_day_tmp = (get_user_now().date() - _recovery_active.started_at.date()).days + 1
        _cur_day_tmp = max(_cur_day_tmp, 1)
        _recovery_header = (
            f"🧘 Восстановление · день {_cur_day_tmp} "
            f"из {_recovery_active.total_days}\n"
            f"<b>Лимит на сегодня: {_target_int} ₽</b>"
        )
        _after_restoration = (
            f"\n\nПосле восстановления — обычный лимит {int(_recovery_active.baseline)} ₽/день."
        )
        text = (
            f"<b>{phrases.STATUS_BALANCE_TITLE}</b> · {zone_emoji} {zone_label}\n\n"
            f"<b>{phrases.STATUS_TODAY_TITLE}</b>\n"
            f"{_recovery_header}\n"
            f"{today_line} · {spent_line}{expenses_block}"
            f"{_after_restoration}\n\n"
            f"<b>{phrases.STATUS_PERIOD_TITLE.format(end=period_end_str, days=days_left)}</b>\n"
            f"{_remaining_period_line} · Прогноз: {int(dl_pred):,}\n"
            f"{reserves_block}"
        )
    else:
        text = (
            f"<b>{phrases.STATUS_BALANCE_TITLE}</b> · {zone_emoji} {zone_label}\n\n"
            f"<b>{phrases.STATUS_TODAY_TITLE}</b>\n"
            f"{today_line} · {spent_line}{expenses_block}\n\n"
            f"<b>{phrases.STATUS_PERIOD_TITLE.format(end=period_end_str, days=days_left)}</b>\n"
            f"{_remaining_period_line}"
            f"{reserves_block}"
        )

    recovery_block = ""
    recovery_kb_extra: InlineKeyboardMarkup | None = None
    if settings.RECOVERY_ENABLED and budget:
        try:
            if _recovery_active is not None:
                active = _recovery_active
                cur_day = (get_user_now().date() - active.started_at.date()).days + 1
                cur_day = max(cur_day, 1)
                tail = max(days_left - active.total_days, 0)
                baseline_int = int(active.baseline)
                recovery_block = f"\n\n{phrases.RECOVERY_DAILY_ACTIVE.format(cur=cur_day, total=active.total_days, target=int(active.target), days=active.total_days, days_word=_plural_days(active.total_days), baseline=baseline_int, tail=tail, tail_word=_plural_days(tail))}"  # noqa: E501
                from ..keyboards import get_recovery_active_keyboard

                recovery_kb_extra = get_recovery_active_keyboard()
            elif _recovery_offer:
                recovery_block = f"\n\n{phrases.RECOVERY_DAILY_OFFER.format(dl_pred=int(dl_pred))}"
                from ..keyboards import get_recovery_plan_keyboard

                recovery_kb_extra = get_recovery_plan_keyboard()
        except Exception as e:
            logging.error("Recovery render failed", exc_info=e)

    if recovery_block:
        text += recovery_block

    # Zone footer hidden when recovery offer/active (priority B)
    if _recovery_active is not None or _recovery_offer:
        footer = "Идём по плану 👍"
        btns = "REGULAR"
    elif end_of_period:
        if money_for_life <= 0:
            footer = random.choice(
                [
                    phrases.STATUS_FOOTER_END_EMPTY_1,
                    phrases.STATUS_FOOTER_END_EMPTY_2,
                    phrases.STATUS_FOOTER_END_EMPTY_3,
                ]
            )
            btns = "REGULAR"
        else:
            footer = random.choice(
                [
                    phrases.STATUS_FOOTER_END_OK_1,
                    phrases.STATUS_FOOTER_END_OK_2,
                    phrases.STATUS_FOOTER_END_OK_3,
                ]
            )
            btns = "REGULAR"
    elif pct_pred > 80:
        footer = random.choice(
            [
                phrases.STATUS_FOOTER_GREEN_1.format(limit=f"{int(dl_pred):,}"),
                phrases.STATUS_FOOTER_GREEN_2,
                phrases.STATUS_FOOTER_GREEN_3,
            ]
        )
        btns = "REGULAR"
    elif pct_pred >= 51:
        footer = random.choice(
            [
                phrases.STATUS_FOOTER_YELLOW_LIGHT_1.format(limit=f"{int(dl_pred):,}"),
                phrases.STATUS_FOOTER_YELLOW_LIGHT_2.format(limit=f"{int(dl_pred):,}"),
                phrases.STATUS_FOOTER_YELLOW_LIGHT_3.format(limit=f"{int(dl_pred):,}"),
            ]
        )
        btns = "REGULAR"
    elif pct_pred >= 26:
        footer = random.choice(
            [
                phrases.STATUS_FOOTER_YELLOW_NONE_1.format(limit=f"{int(dl_pred):,}"),
                phrases.STATUS_FOOTER_YELLOW_NONE_2.format(limit=f"{int(dl_pred):,}"),
                phrases.STATUS_FOOTER_YELLOW_NONE_3.format(limit=f"{int(dl_pred):,}"),
            ]
        )
        btns = "REGULAR"
    else:
        footer = random.choice(
            [
                phrases.STATUS_FOOTER_RED_NONE_1.format(limit=f"{int(dl_pred):,}"),
                phrases.STATUS_FOOTER_RED_NONE_2.format(limit=f"{int(dl_pred):,}"),
                phrases.STATUS_FOOTER_RED_NONE_3.format(limit=f"{int(dl_pred):,}"),
            ]
        )
        btns = "REGULAR"

    base_kb = _build_status_keyboard(btns, tg_id)
    if recovery_kb_extra is not None:
        merged = list(base_kb.inline_keyboard) + list(recovery_kb_extra.inline_keyboard)
        kb = InlineKeyboardMarkup(inline_keyboard=merged)
    else:
        kb = base_kb
    return text + "\n\n" + footer if footer else text, kb


def _build_status_keyboard(btn_type: str, tg_id: int) -> InlineKeyboardMarkup:
    if settings.EXPENSE_SIMPLE_CHECK:
        return InlineKeyboardMarkup(inline_keyboard=[])
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=phrases.BTN_BACK_MAIN, callback_data="menu_back")],
        ]
    )


# ============ RECOVERY ============


def _recovery_days_word(n: int) -> str:
    return _plural_days(n)


@router.callback_query(F.data == "recovery:show_options")
async def recovery_show_options(callback: CallbackQuery):
    if not settings.RECOVERY_ENABLED:
        await callback.answer()
        return
    await callback.answer()
    tg_id = callback.from_user.id
    budget = await get_budget_or_none(tg_id)
    if not budget:
        await callback.message.edit_text(
            text=phrases.NO_BUDGET, reply_markup=await get_main_menu_keyboard(tg_id)
        )
        return
    from ...services.budget_service import resolve_frozen_baseline
    from ...services.recovery_service import calculate_recovery_options, get_active_recovery

    active = await get_active_recovery(tg_id)
    if active:
        text, kb = await _build_status(tg_id)
        await callback.message.edit_text(text=text, reply_markup=kb)
        return
    b_val = await resolve_frozen_baseline(budget)
    days_left = budget.days_remaining
    from ...services.budget_service import get_money_for_life, get_period_spent

    spent_period = await get_period_spent(tg_id, budget)
    money_for_life = get_money_for_life(budget, spent_period)
    opts = calculate_recovery_options(b_val, money_for_life, days_left)
    if not opts:
        await callback.answer(phrases.RECOVERY_PERIOD_END, show_alert=True)
        return
    from ..keyboards import get_recovery_offer_keyboard, get_recovery_single_keyboard

    if len(opts) == 1:
        opt = opts[0]
        tail = opt.tail_days
        icon = "⚡" if opt.level == "fast" else "⚖️" if opt.level == "balanced" else "🌿"
        option_line = phrases.RECOVERY_OPTION_LINE.format(
            icon=icon,
            label=opt.level,
            target=int(opt.target),
            days=opt.days,
            days_word=_plural_days(opt.days),
        )
        tail_line = phrases.RECOVERY_TAIL_LINE_OFFER.format(
            baseline=int(b_val), tail=tail, tail_word=_plural_days(tail)
        )
        text = (
            f"{phrases.RECOVERY_OFFER_TITLE}\n"
            f"{phrases.RECOVERY_BASELINE.format(amount=int(b_val))}\n"
            f"{phrases.RECOVERY_OFFER_SINGLE}\n"
            f"{option_line}\n"
            f"{tail_line}"
        )
        kb = get_recovery_single_keyboard(opt.level)
    else:
        lines = [
            phrases.RECOVERY_OFFER_TITLE,
            phrases.RECOVERY_BASELINE.format(amount=int(b_val)),
            phrases.RECOVERY_OFFER_MULTI,
        ]
        icon_map = {"fast": "⚡", "balanced": "⚖️", "soft": "🌿"}
        for opt in opts:
            lines.append(
                phrases.RECOVERY_OPTION_LINE.format(
                    icon=icon_map.get(opt.level, ""),
                    label=opt.level,
                    target=int(opt.target),
                    days=opt.days,
                    days_word=_plural_days(opt.days),
                )
            )
            lines.append(
                phrases.RECOVERY_TAIL_LINE_OFFER.format(
                    baseline=int(b_val), tail=opt.tail_days, tail_word=_plural_days(opt.tail_days)
                )
            )
        text = "\n".join(lines)
        kb = get_recovery_offer_keyboard(opts)
    await callback.message.edit_text(text=text, reply_markup=kb)


@router.callback_query(F.data.startswith("recovery:choose:"))
async def recovery_choose(callback: CallbackQuery):
    if not settings.RECOVERY_ENABLED:
        await callback.answer()
        return
    await callback.answer()
    level = callback.data.split(":")[-1]
    if level not in ("fast", "balanced", "soft"):
        await callback.answer(phrases.ERR_INVALID_DATA, show_alert=True)
        return
    tg_id = callback.from_user.id
    budget = await get_budget_or_none(tg_id)
    if not budget:
        await callback.message.edit_text(
            text=phrases.NO_BUDGET, reply_markup=await get_main_menu_keyboard(tg_id)
        )
        return
    from ...services.budget_service import resolve_frozen_baseline
    from ...services.recovery_service import (
        calculate_recovery_options,
        create_recovery,
        get_active_recovery,
    )

    if await get_active_recovery(tg_id):
        await callback.answer(phrases.RECOVERY_ALREADY_ACTIVE, show_alert=True)
        return
    b_val = await resolve_frozen_baseline(budget)
    days_left = budget.days_remaining
    from ...services.budget_service import get_money_for_life, get_period_spent

    spent_period = await get_period_spent(tg_id, budget)
    money_for_life = get_money_for_life(budget, spent_period)
    opts = calculate_recovery_options(b_val, money_for_life, days_left)
    chosen = next((o for o in opts if o.level == level), None)
    if not chosen:
        # re-render actual options
        if not opts:
            await callback.message.edit_text(
                text=phrases.RECOVERY_PERIOD_END, reply_markup=await get_main_menu_keyboard(tg_id)
            )
            return
        from ..keyboards import get_recovery_offer_keyboard, get_recovery_single_keyboard

        if len(opts) == 1:
            opt = opts[0]
            option_line = phrases.RECOVERY_OPTION_LINE.format(
                icon="⚡",
                label=opt.level,
                target=int(opt.target),
                days=opt.days,
                days_word=_plural_days(opt.days),
            )
            tail_line = phrases.RECOVERY_TAIL_LINE_OFFER.format(
                baseline=int(b_val),
                tail=opt.tail_days,
                tail_word=_plural_days(opt.tail_days),
            )
            text = (
                f"{phrases.RECOVERY_OFFER_TITLE}\n"
                f"{phrases.RECOVERY_BASELINE.format(amount=int(b_val))}\n"
                f"{phrases.RECOVERY_OFFER_SINGLE}\n"
                f"{option_line}\n"
                f"{tail_line}"
            )
            kb = get_recovery_single_keyboard(opt.level)
        else:
            icon_map = {"fast": "⚡", "balanced": "⚖️", "soft": "🌿"}
            lines = [
                phrases.RECOVERY_OFFER_TITLE,
                phrases.RECOVERY_BASELINE.format(amount=int(b_val)),
                phrases.RECOVERY_OFFER_MULTI,
            ]
            for opt in opts:
                lines.append(
                    phrases.RECOVERY_OPTION_LINE.format(
                        icon=icon_map.get(opt.level, ""),
                        label=opt.level,
                        target=int(opt.target),
                        days=opt.days,
                        days_word=_plural_days(opt.days),
                    )
                )
                lines.append(
                    phrases.RECOVERY_TAIL_LINE_OFFER.format(
                        baseline=int(b_val),
                        tail=opt.tail_days,
                        tail_word=_plural_days(opt.tail_days),
                    )
                )
            text = "\n".join(lines)
            kb = get_recovery_offer_keyboard(opts)
        await callback.message.edit_text(text=text, reply_markup=kb)
        await callback.answer(phrases.RECOVERY_OPTION_STALE, show_alert=True)
        return
    deficit = max(b_val * days_left - money_for_life, 0)
    await create_recovery(tg_id, budget.id, b_val, chosen.target, chosen.days, deficit)
    await callback.message.edit_text(
        text=phrases.RECOVERY_CHOSEN, reply_markup=await get_main_menu_keyboard(tg_id)
    )
    text, kb = await _build_status(tg_id)
    await callback.message.answer(text=text, reply_markup=kb)


@router.callback_query(F.data == "recovery:dismiss")
async def recovery_dismiss(callback: CallbackQuery):
    if not settings.RECOVERY_ENABLED:
        await callback.answer()
        return
    await callback.answer()
    tg_id = callback.from_user.id
    budget = await get_budget_or_none(tg_id)
    if not budget:
        await callback.message.edit_text(
            text=phrases.NO_BUDGET, reply_markup=await get_main_menu_keyboard(tg_id)
        )
        return
    from ...services.budget_service import resolve_frozen_baseline
    from ...services.recovery_service import dismiss_offer

    b_val = await resolve_frozen_baseline(budget)
    days_left = budget.days_remaining
    from ...services.budget_service import get_money_for_life, get_period_spent

    spent_period = await get_period_spent(tg_id, budget)
    money_for_life = get_money_for_life(budget, spent_period)
    deficit = max(b_val * days_left - money_for_life, 0)
    await dismiss_offer(tg_id, deficit)
    await callback.message.edit_text(
        text=phrases.RECOVERY_DISMISSED, reply_markup=await get_main_menu_keyboard(tg_id)
    )


@router.callback_query(F.data == "recovery:stop")
async def recovery_stop(callback: CallbackQuery):
    if not settings.RECOVERY_ENABLED:
        await callback.answer()
        return
    await callback.answer()
    from ...services.recovery_service import stop_recovery

    await stop_recovery(callback.from_user.id)
    await callback.message.edit_text(
        text=phrases.RECOVERY_STOPPED,
        reply_markup=await get_main_menu_keyboard(callback.from_user.id),
    )
    text, kb = await _build_status(callback.from_user.id)
    await callback.message.answer(text=text, reply_markup=kb)


# ============ ONBOARDING / SKIP ============


@router.callback_query(F.data == "skip_step")
async def skip_step(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    current_state = await state.get_state()

    if current_state == BudgetSetup.waiting_for_period_start.state:
        await state.update_data(period_start_day=1)
        await _finish_onboarding(callback, state)
    elif current_state == BudgetSetup.waiting_for_mandatory.state:
        await state.update_data(mandatory=0)
        await _advance_onboarding(callback, state)
    elif current_state == BudgetSetup.waiting_for_black_day.state:
        await state.update_data(black_day=0)
        await _advance_onboarding(callback, state)
    elif current_state == BudgetSetup.waiting_for_wishlist_name.state:
        await state.update_data(wishlist_name="", wishlist_price=0)
        await _advance_onboarding(callback, state)
    elif current_state == BudgetSetup.waiting_for_rounding_mode.state:
        await state.update_data(rounding_mode=0)
        await _finish_onboarding(callback, state)
    else:
        await callback.answer()


async def _advance_onboarding(source: CallbackQuery | Message, state: FSMContext):
    current_state = await state.get_state()

    if current_state == BudgetSetup.waiting_for_period_start.state:
        await state.set_state(BudgetSetup.waiting_for_mandatory)
        text = phrases.ONBOARDING_PERIOD_DONE
        if isinstance(source, CallbackQuery):
            await source.message.edit_text(text=text, reply_markup=get_onboarding_keyboard())
        else:
            await source.answer(text=text, reply_markup=get_onboarding_keyboard())
    elif current_state == BudgetSetup.waiting_for_mandatory.state:
        await state.set_state(BudgetSetup.waiting_for_black_day)
        kw = get_onboarding_keyboard() if isinstance(source, CallbackQuery) else None
        text = phrases.ONBOARDING_MANDATORY_PROMPT
        if isinstance(source, CallbackQuery):
            await source.message.edit_text(text=text, reply_markup=kw)
        else:
            await source.answer(text=text, reply_markup=get_onboarding_keyboard())
    elif current_state == BudgetSetup.waiting_for_black_day.state:
        await state.set_state(BudgetSetup.waiting_for_wishlist_name)
        text = phrases.ONBOARDING_WISHLIST_PROMPT
        if isinstance(source, CallbackQuery):
            await source.message.edit_text(text=text, reply_markup=get_onboarding_keyboard())
        else:
            await source.answer(text=text, reply_markup=get_onboarding_keyboard())
    elif current_state == BudgetSetup.waiting_for_wishlist_name.state:
        await state.set_state(BudgetSetup.waiting_for_rounding_mode)
        kw = get_rounding_mode_keyboard()
        text = phrases.ONBOARDING_ROUNDING_PROMPT
        if isinstance(source, CallbackQuery):
            await source.message.edit_text(text=text, reply_markup=kw)
        else:
            await source.answer(text=text, reply_markup=kw)
    elif current_state == BudgetSetup.waiting_for_rounding_mode.state:
        await state.update_data(rounding_mode=0)
        await _finish_onboarding(source, state)


async def _finish_onboarding(source: CallbackQuery | Message, state: FSMContext):
    data = await state.get_data()
    telegram_id = source.from_user.id if isinstance(source, CallbackQuery) else source.from_user.id

    try:
        await get_or_create_user(
            telegram_id=telegram_id,
            first_name=source.from_user.first_name,
            username=source.from_user.username,
        )
    except Exception:
        text = phrases.ERR_DB
        if isinstance(source, CallbackQuery):
            await source.message.edit_text(text=text)
        else:
            await source.answer(text=text)
        await state.clear()
        return

    month = get_msk_now().strftime("%Y-%m")
    wishlist_name = (
        data.get("wishlist_name", phrases.DEFAULT_WISHLIST_NAME) or phrases.DEFAULT_WISHLIST_NAME
    )
    wishlist_price = data.get("wishlist_price", 0)
    period_start_day = data.get("period_start_day", 1)

    await save_budget(
        telegram_id=telegram_id,
        month=month,
        income=data.get("income", 0),
        mandatory=data.get("mandatory", 0),
        black_day=data.get("black_day", 0),
        wishlist_name=wishlist_name,
        wishlist_price=wishlist_price,
        period_start_day=period_start_day,
    )

    rounding_mode = data.get("rounding_mode", 0)
    async with async_session_maker() as session:
        settings_result = await session.execute(
            select(UserSettings).where(UserSettings.telegram_id == telegram_id)
        )
        user_settings = settings_result.scalar_one_or_none()
        if user_settings:
            user_settings.rounding_mode = rounding_mode
        else:
            session.add(UserSettings(telegram_id=telegram_id, rounding_mode=rounding_mode))
        await session.commit()

    import calendar

    today = get_msk_now()
    available = data.get("income", 0) - data.get("mandatory", 0) - data.get("black_day", 0)
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    clamped_start = min(period_start_day, days_in_month)
    if clamped_start == 1:
        days_remaining = max(days_in_month - today.day + 1, 0)
    elif today.day >= clamped_start:
        remaining_this = days_in_month - today.day
        days_remaining = remaining_this + clamped_start
    else:
        days_remaining = clamped_start - today.day
    daily_limit = max(available / max(days_remaining, 1), 0)

    text = phrases.STATUS_BUDGET_COMPLETE.format(
        month=month,
        income=f"{data.get('income', 0):,.0f}",
        limit=f"{daily_limit:,.0f}",
        hint=phrases.ONBOARDING_HINT_SETTINGS,
    )

    kb = await get_main_menu_keyboard(telegram_id)
    if isinstance(source, CallbackQuery):
        await source.message.edit_text(text=text, reply_markup=kb)
    else:
        await source.answer(text=text, reply_markup=kb)

    if settings.EXPENSE_SIMPLE_CHECK:
        if isinstance(source, CallbackQuery):
            await source.message.answer(
                text=phrases.WELCOME_MENU,
                reply_markup=get_main_reply_keyboard(),
            )
        else:
            await source.answer(
                text=phrases.WELCOME_MENU,
                reply_markup=get_main_reply_keyboard(),
            )

    await state.clear()


# ============ BUDGET SETUP STEPS ============


@router.message(BudgetSetup.waiting_for_income)
async def process_income(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text)
    except ValueError:
        await handle_invalid_input(
            message, state, phrases.ERR_INVALID_NUMBER.format(example="50000")
        )
        return

    await state.update_data(income=amount)
    await state.set_state(BudgetSetup.waiting_for_period_start)
    await message.answer(
        text=f"{phrases.ONBOARDING_INCOME_ACCEPTED}\n\n{phrases.PERIOD_START_CHOICE}",
        reply_markup=get_period_start_keyboard(),
    )


@router.callback_query(F.data.in_(["period_today", "period_first", "period_other"]))
async def handle_period_start_choice(callback: CallbackQuery, state: FSMContext):
    import calendar

    today = get_msk_now()
    current_state = await state.get_state()

    if callback.data == "period_other":
        await callback.message.edit_text(
            text=phrases.PERIOD_CUSTOM_PROMPT, reply_markup=get_cancel_keyboard()
        )
        await callback.answer()
        return

    if callback.data == "period_today":
        day = today.day
    else:  # period_first
        day = 1

    days_in_month = calendar.monthrange(today.year, today.month)[1]
    if day > days_in_month:
        day = days_in_month

    if current_state == BudgetSetup.waiting_for_period_start.state:
        await state.update_data(period_start_day=day)
        await _finish_onboarding(callback, state)
    elif current_state == EditBudget.waiting_for_period_start.state:
        await update_budget_field(callback.from_user.id, "period_start_day", day)
        await callback.message.edit_text(
            text=phrases.PERIOD_UPDATED.format(day=day),
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )
        await state.clear()

    await callback.answer()


@router.message(BudgetSetup.waiting_for_period_start, F.text.in_(REPLY_MENU_COMMANDS))
async def handle_menu_interrupt_in_budget_setup(message: Message, state: FSMContext):
    await message.answer(
        phrases.FSM_INTERRUPT_PERIOD,
        reply_markup=get_cancel_keyboard(),
    )


@router.message(BudgetSetup.waiting_for_period_start)
async def process_period_start(message: Message, state: FSMContext):
    import calendar

    today = get_msk_now()
    try:
        day = int(message.text.strip())
    except (ValueError, TypeError):
        await handle_invalid_input(message, state, phrases.ERR_INVALID_NUMBER.format(example="25"))
        return

    if day < 1:
        day = 1
    elif day > 31:
        day = 31

    days_in_month = calendar.monthrange(today.year, today.month)[1]
    if day > days_in_month:
        day = days_in_month

    await state.update_data(period_start_day=day)
    await _finish_onboarding(message, state)


@router.message(BudgetSetup.waiting_for_mandatory)
async def process_mandatory(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text, allow_zero=True)
    except (ValueError, TypeError):
        await handle_invalid_input(
            message, state, phrases.ERR_INVALID_NUMBER.format(example="15000")
        )
        return

    await state.update_data(mandatory=amount)
    await state.set_state(BudgetSetup.waiting_for_black_day)
    await message.answer(
        text=phrases.ONBOARDING_MANDATORY_PROMPT, reply_markup=get_onboarding_keyboard()
    )


@router.message(BudgetSetup.waiting_for_black_day)
async def process_black_day(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text, allow_zero=True)
    except ValueError:
        await handle_invalid_input(
            message, state, phrases.ERR_INVALID_NUMBER.format(example="5000")
        )
        return

    await state.update_data(black_day=amount)
    await state.set_state(BudgetSetup.waiting_for_wishlist_name)
    await message.answer(
        text=phrases.ONBOARDING_WISHLIST_PROMPT, reply_markup=get_onboarding_keyboard()
    )


def _parse_wishlist(text: str) -> tuple[str, float]:
    numbers = re.findall(r"[\d ]+", text.replace(",", "."))
    name = text
    price = 0
    for num_str in numbers:
        try:
            price = float(num_str.replace(" ", ""))
            name = text.replace(num_str, "").strip()
            break
        except (ValueError, TypeError):
            continue
    if not name:
        name = phrases.DEFAULT_WISHLIST_NAME
    elif name[0].islower():
        name = name[0].upper() + name[1:]
    return name, price


@router.message(BudgetSetup.waiting_for_wishlist_name)
async def process_wishlist_name(message: Message, state: FSMContext):
    name, price = _parse_wishlist(message.text.strip())
    await state.update_data(wishlist_name=name, wishlist_price=price)
    await _advance_onboarding(message, state)


# ============ ROUNDING MODE ============


@router.callback_query(F.data.in_(["rounding_off", "rounding_10", "rounding_100"]))
async def handle_rounding_choice(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    mode_map = {"rounding_off": 0, "rounding_10": 10, "rounding_100": 100}
    mode = mode_map[callback.data]
    current_state = await state.get_state()
    if current_state == BudgetSetup.waiting_for_rounding_mode.state:
        await state.update_data(rounding_mode=mode)
        await _finish_onboarding(callback, state)
        return
    async with async_session_maker() as session:
        result = await session.execute(
            select(UserSettings).where(UserSettings.telegram_id == callback.from_user.id)
        )
        settings = result.scalar_one_or_none()
        if settings:
            settings.rounding_mode = mode
        else:
            session.add(UserSettings(telegram_id=callback.from_user.id, rounding_mode=mode))
        await session.commit()
    label = phrases.ROUNDING_LABEL_OFF if mode == 0 else f"{mode} ₽"
    await callback.message.edit_text(
        text=phrases.ROUNDING_SAVED.format(label=label),
        reply_markup=await get_main_menu_keyboard(callback.from_user.id),
    )


# ============ NEW PERIOD SETUP (SMART ROLLOVER) ============


async def _advance_new_period(source: CallbackQuery | Message, state: FSMContext):
    current = await state.get_state()
    if current == NewPeriodSetup.waiting_for_income.state:
        data = await state.get_data()
        old_date = data.get("old_date", 1)
        text = phrases.ROLLOVER_KEEP_DATE_PROMPT.format(date=old_date)
        if isinstance(source, CallbackQuery):
            await source.message.answer(text=text, reply_markup=get_keep_date_keyboard(old_date))
        else:
            await source.answer(text=text, reply_markup=get_keep_date_keyboard(old_date))
        await state.set_state(NewPeriodSetup.waiting_for_period_start)
    elif current == NewPeriodSetup.waiting_for_period_start.state:
        await _finish_new_period(source, state)


async def _finish_new_period(source: CallbackQuery | Message, state: FSMContext):
    data = await state.get_data()
    income = data.get("income", 0)
    period_start_day = data.get("period_start_day", 1)
    tg_id = source.from_user.id

    from ...services.monthly_report import get_all_budgets

    budgets = await get_all_budgets(tg_id)
    if budgets:
        old = budgets[0]
        mandatory = old.mandatory_payments
        wishlist_name = old.wishlist_name or phrases.DEFAULT_WISHLIST_NAME
        wishlist_target = old.wishlist_target
    else:
        mandatory = 0
        wishlist_name = phrases.DEFAULT_WISHLIST_NAME
        wishlist_target = 0

    month = get_msk_now().strftime("%Y-%m")
    await save_budget(
        telegram_id=tg_id,
        month=month,
        income=income,
        mandatory=mandatory,
        black_day=0,
        wishlist_name=wishlist_name,
        wishlist_price=wishlist_target,
        period_start_day=period_start_day,
    )
    if settings.RECOVERY_ENABLED and budgets:
        try:
            from ...services.recovery_service import expire_active_recoveries_for_budget

            await expire_active_recoveries_for_budget(budgets[0].id)
        except Exception:
            pass
    await state.clear()

    if isinstance(source, CallbackQuery):
        try:
            await source.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        budget = await get_active_budget(tg_id)
        dl = int(budget.daily_limit) if budget else 0
        await source.message.answer(phrases.ROLLOVER_CONFIRMED.format(daily_limit=dl))
    else:
        budget = await get_active_budget(tg_id)
        dl = int(budget.daily_limit) if budget else 0
        await source.answer(phrases.ROLLOVER_CONFIRMED.format(daily_limit=dl))


@router.callback_query(F.data == "rollover_keep_income")
async def handle_rollover_keep_income(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    income = data.get("old_income", 0)
    await state.update_data(income=income)
    await _advance_new_period(callback, state)


@router.callback_query(F.data == "rollover_keep_date")
async def handle_rollover_keep_date(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    period_start_day = data.get("old_date", 1)
    await state.update_data(period_start_day=period_start_day)
    await _advance_new_period(callback, state)


@router.message(NewPeriodSetup.waiting_for_income)
async def new_period_income(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text.strip())
    except ValueError:
        await handle_invalid_input(
            message, state, phrases.ERR_INVALID_NUMBER.format(example="50000")
        )
        return
    if amount is None or amount <= 0:
        await message.answer(phrases.ERR_INVALID_NUMBER.format(example="50000"))
        return
    await state.update_data(income=amount)
    await _advance_new_period(message, state)


@router.message(NewPeriodSetup.waiting_for_period_start, F.text.in_(REPLY_MENU_COMMANDS))
async def handle_new_period_interrupt(message: Message, state: FSMContext):
    await message.answer(
        phrases.FSM_INTERRUPT_PERIOD,
        reply_markup=get_cancel_keyboard(),
    )


@router.message(NewPeriodSetup.waiting_for_period_start)
async def new_period_period_start(message: Message, state: FSMContext):
    text = message.text.strip()
    try:
        day = int(text)
        if day < 1 or day > 31:
            raise ValueError
    except (ValueError, TypeError):
        await handle_invalid_input(message, state, phrases.ERR_INVALID_NUMBER.format(example="20"))
        return
    await state.update_data(period_start_day=day)
    await _advance_new_period(message, state)


# ============ ADD EXPENSE ============


@router.callback_query(F.data == "menu_add")
async def menu_add(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AddExpense.waiting_for_amount)
    await callback.message.edit_text(
        text=phrases.ADD_EXPENSE_PROMPT, reply_markup=get_cancel_keyboard()
    )


async def _save_expenses_from_parsed_list(
    user_id: int,
    reports: list[ExpenseParseReport],
    message: Message,
) -> tuple[bool, bool, list[str], int | None, list[int]]:
    lines = []
    first_id = None
    errors = 0
    all_silent = True
    corrected_ids: list[int] = []

    for report in reports:
        if not report.is_valid:
            continue
        amount = report.amount
        description = report.description or phrases.FALLBACK_DESC

        effective = amount

        if description == phrases.FALLBACK_DESC:
            cat = None
        else:
            try:
                cat, matched = await detect_category_db(description, user_id, amount)
            except Exception as e:
                logging.error("Category detection failed", exc_info=e)
                cat = None

        cat_id = cat.id if cat else None
        emoji, cat_name = get_category_display(cat.name) if cat else phrases.DEFAULT_CATEGORY

        dup_status = dup_middleware.check(user_id, amount, description)
        if dup_status == "silent":
            continue
        if dup_status == "warn":
            dup_middleware.set_pending(
                user_id, effective, description, cat_id, description, emoji, cat_name
            )
            await message.answer(
                phrases.DUP_WARNING.format(amount=f"{effective:,.0f}", desc=safe(description)),
                reply_markup=get_duplicate_keyboard(),
            )
            return True, True, [], None, []

        all_silent = False

        try:
            async with async_session_maker() as session:
                expense = Expense(
                    telegram_id=user_id,
                    amount=effective,
                    description=description or cat_name,
                    category_id=cat_id,
                    date=get_msk_now(),
                )
                session.add(expense)
                await session.commit()
                if first_id is None:
                    first_id = expense.id
        except Exception as e:
            logging.error("Expense insert failed", exc_info=e)
            cause = getattr(e, "__cause__", None)
            if cause:
                logging.error("Caused by: %s: %s", type(cause).__name__, cause)
            errors += 1
            continue

        line = phrases.EXPENSE_SAVED_LINE.format(
            amount=f"{effective:,.0f}", desc=safe(description), emoji=emoji, cat=cat_name
        )
        if report.was_corrected:
            correction_msg = phrases.ERR_MATH_CORRECTED.format(hint=report.correction_hint or "")
            line = f"{line}\n{correction_msg}"
            corrected_ids.append(expense.id)

        dup_middleware.record(
            user_id,
            message.message_id,
            effective,
            description,
            expense.id,
            response_text=line,
        )
        lines.append(line)

    return False, all_silent, lines, first_id, corrected_ids


@router.message(AddExpense.waiting_for_amount)
async def process_expense(message: Message, state: FSMContext):
    text = message.text.strip()
    if text in _REPLY_BTNS:
        await state.clear()
        await handle_reply_menu(message, state)
        return

    await get_or_create_user(
        telegram_id=message.from_user.id,
        first_name=message.from_user.first_name,
        username=message.from_user.username,
    )

    result = parse_multi_expense_text(text)
    if not result.reports:
        return

    user_id = message.from_user.id

    if not result.is_fully_valid:
        invalid = next((r for r in result.reports if not r.is_valid), None)
        if invalid and invalid.error_type == "MATH_ERROR":
            await handle_invalid_input(
                message,
                state,
                phrases.ERR_MATH_ERROR.format(detail=invalid.error_detail or invalid.raw_text),
            )
            return
        return

    if len(result.reports) == 1:
        report = result.reports[0]
        dup_status = dup_middleware.check(user_id, report.amount, report.description)
        if dup_status != "new":
            if dup_status == "silent":
                await state.clear()
                return
            description = report.description or phrases.FALLBACK_DESC
            if description == phrases.FALLBACK_DESC:
                cat = None
            else:
                try:
                    cat, _ = await detect_category_db(description, user_id, report.amount)
                except Exception as e:
                    logging.error("Category detection failed", exc_info=e)
                    cat = None
            cat_id = cat.id if cat else None
            emoji, cat_name = get_category_display(cat.name) if cat else phrases.DEFAULT_CATEGORY
            dup_middleware.set_pending(
                user_id, report.amount, description, cat_id, description, emoji, cat_name
            )
            await message.answer(
                phrases.DUP_WARNING.format(amount=f"{report.amount:,.0f}", desc=safe(description)),
                reply_markup=get_duplicate_keyboard(),
            )
            return

    (
        sent_dup,
        all_silent,
        lines,
        first_id,
        corrected_ids,
    ) = await _save_expenses_from_parsed_list(user_id, result.reports, message)
    if sent_dup:
        return

    if all_silent:
        return

    if not lines:
        await message.answer(phrases.ERR_EXPENSE_SAVE)
        return

    kb = _build_expense_check_kb(first_id, len(lines), corrected_ids)

    response_text = phrases.EXPENSE_SAVED_ALL.format(lines="\n".join(lines), round_up="")
    await message.answer(text=response_text, reply_markup=kb)
    await state.clear()


# ============ CATEGORY CHANGE ============


@router.callback_query(F.data.startswith("change_cat:"))
async def change_category(callback: CallbackQuery):
    await callback.answer()
    try:
        expense_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError, TypeError):
        await callback.message.edit_text(
            text=phrases.ERR_INVALID_DATA,
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )
        return

    categories = await get_user_categories(callback.from_user.id)

    buttons = []
    row = []
    for i, cat in enumerate(categories):
        emoji, display_text = get_category_display(cat.name)
        row.append(
            InlineKeyboardButton(
                text=f"{emoji} {display_text}",
                callback_data=f"set_cat:{expense_id}:{cat.id}",
            )
        )
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append(
        [InlineKeyboardButton(text=phrases.BTN_NEW_CATEGORY, callback_data=f"new_cat:{expense_id}")]
    )
    if not settings.EXPENSE_SIMPLE_CHECK:
        buttons.append(
            [
                InlineKeyboardButton(
                    text=phrases.BTN_BACK, callback_data=f"exp_back_cat:{expense_id}"
                )
            ]
        )

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(
        text=phrases.CATEGORY_PICKER,
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("set_cat:"))
async def set_category(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.message.edit_text(
            text=phrases.ERR_INVALID_DATA,
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )
        return
    _, expense_id_str, category_id_str = parts
    try:
        expense_id = int(expense_id_str)
        category_id = int(category_id_str)
    except (ValueError, TypeError):
        await callback.message.edit_text(
            text=phrases.ERR_INVALID_DATA,
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )
        return

    async with async_session_maker() as session:
        result = await session.execute(
            select(Expense).where(
                Expense.id == expense_id,
                Expense.telegram_id == callback.from_user.id,
                Expense.is_deleted == False,
            )
        )
        expense = result.scalar_one_or_none()
        if not expense:
            await callback.message.edit_text(
                text=phrases.ERR_EXPENSE_NOT_FOUND,
                reply_markup=await get_main_menu_keyboard(callback.from_user.id),
            )
            return

        result = await session.execute(
            select(Category).where(
                Category.id == category_id,
                (Category.telegram_id == callback.from_user.id) | (Category.telegram_id == None),  # noqa: E711 — SQLAlchemy IS NULL
            )
        )
        cat = result.scalar_one_or_none()
        if not cat:
            await callback.message.edit_text(
                text=phrases.ERR_CATEGORY_NOT_FOUND,
                reply_markup=await get_main_menu_keyboard(callback.from_user.id),
            )
            return

        expense.category_id = category_id
        await session.commit()

    await add_keyword_to_category(
        callback.from_user.id,
        category_id,
        expense.description or "",
    )

    emoji, cat_name = get_category_display(cat.name)
    await callback.message.edit_text(
        text=phrases.CATEGORY_CHANGED.format(
            amount=f"{expense.amount:,.0f}",
            desc=safe(expense.description or cat_name),
            emoji=emoji,
            cat=cat_name,
        ),
        reply_markup=await get_main_menu_keyboard(callback.from_user.id),
    )


@router.callback_query(F.data.startswith("exp_back_cat:"))
async def back_from_category_change(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if settings.EXPENSE_SIMPLE_CHECK:
        return
    await state.clear()
    await callback.message.edit_text(
        text=phrases.BACK_NAV,
        reply_markup=await get_main_menu_keyboard(callback.from_user.id),
    )


@router.callback_query(F.data.startswith("new_cat:"))
async def new_category_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        expense_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError, TypeError):
        await callback.message.edit_text(
            text=phrases.ERR_INVALID_DATA,
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )
        return
    await state.update_data(new_cat_expense_id=expense_id)
    await state.set_state(CustomCategory.waiting_for_name)
    await callback.message.edit_text(
        text=phrases.NEW_CATEGORY_PROMPT,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=phrases.BTN_CANCEL, callback_data="cancel")],
            ]
        ),
    )


@router.message(CustomCategory.waiting_for_name)
async def save_new_category(message: Message, state: FSMContext):
    raw = message.text.strip()
    name = build_category_name(raw)
    if not name or len(name) > 30:
        await message.answer(
            phrases.ERR_NAME_LENGTH,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=phrases.BTN_CANCEL, callback_data="cancel")],
                ]
            ),
        )
        return

    data = await state.get_data()
    expense_id = data.get("new_cat_expense_id")
    if not expense_id:
        await state.clear()
        return

    async with async_session_maker() as session:
        existing = await session.execute(
            select(Category).where(
                Category.telegram_id == message.from_user.id,
                Category.name == name,
            )
        )
        if existing.scalar_one_or_none():
            await message.answer(
                text=phrases.ERR_CATEGORY_EXISTS.format(name=name),
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text=phrases.BTN_CANCEL, callback_data="cancel")],
                    ]
                ),
            )
            return

        result = await session.execute(
            select(Expense).where(
                Expense.id == expense_id,
                Expense.telegram_id == message.from_user.id,
                Expense.is_deleted == False,
            )
        )
        expense = result.scalar_one_or_none()
        if not expense:
            await message.answer(phrases.ERR_EXPENSE_NOT_FOUND)
            await state.clear()
            return

        cat = Category(
            telegram_id=message.from_user.id,
            name=name,
            keywords=_dump_keywords([clean_and_normalize(expense.description or "")]),
        )
        session.add(cat)
        await session.flush()
        expense.category_id = cat.id
        await session.commit()

    await state.clear()
    await message.answer(
        text=phrases.CATEGORY_CREATED.format(name=name, desc=expense.description),
        reply_markup=await get_main_menu_keyboard(message.from_user.id),
    )


# ============ OVERDRAFT / MORNING HANDLERS ============


@router.callback_query(F.data.startswith("fix_overdraft:"))
async def handle_fix_overdraft(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) < 2:
        await callback.message.edit_text(
            text=phrases.ERR_INVALID_DATA,
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )
        return
    action = parts[1]

    if action == "reduce_limit":
        await callback.message.edit_text(
            text=phrases.REDUCE_LIMIT_ACCEPTED,
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )
        return

    try:
        overdraft = float(parts[2])
    except (IndexError, ValueError, TypeError):
        await callback.message.edit_text(
            text=phrases.ERR_INVALID_DATA,
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )
        return
    if action == "wishlist":
        async with async_session_maker() as session:
            result = await session.execute(
                select(Wishlist)
                .where(Wishlist.telegram_id == callback.from_user.id, Wishlist.is_active == True)
                .order_by(Wishlist.id)
                .limit(1)
            )
            goal = result.scalar_one_or_none()
            if goal and goal.current_amount > 0:
                deduction = min(overdraft, goal.current_amount)
                goal.current_amount -= deduction
                await session.commit()
                text = phrases.COVERED_FROM_WISHLIST.format(
                    amount=int(deduction), remain=int(goal.current_amount)
                )
            else:
                text = phrases.ERR_WISHLIST_EMPTY
        await callback.message.edit_text(
            text=text, reply_markup=await get_main_menu_keyboard(callback.from_user.id)
        )

    elif action == "cubyshka":
        await callback.message.edit_text(
            text=phrases.ERR_GENERIC,
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )


@router.callback_query(F.data == "recalc_limit")
async def recalc_limit(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(EditBudget.waiting_for_recalc_balance)
    await callback.message.answer(
        text=phrases.RECALC_LIMIT_PROMPT,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=phrases.BTN_CANCEL, callback_data="cancel")],
            ]
        ),
    )


@router.callback_query(F.data == "change_budget")
async def change_budget(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text(
        text=phrases.CHANGE_BUDGET_CHOICE,
        reply_markup=get_change_budget_choice_keyboard(),
    )


@router.callback_query(F.data == "change_budget_add")
async def change_budget_add(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(EditBudget.waiting_for_add_income)
    await callback.message.edit_text(
        text=phrases.INCOME_ADD_PROMPT, reply_markup=get_cancel_keyboard()
    )


@router.callback_query(F.data == "change_budget_recalc")
async def change_budget_recalc(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(EditBudget.waiting_for_recalc_balance)
    await callback.message.edit_text(
        text=phrases.RECALC_LIMIT_PROMPT,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=phrases.BTN_CANCEL, callback_data="cancel")],
            ]
        ),
    )


@router.message(EditBudget.waiting_for_recalc_balance)
async def save_recalc_balance(message: Message, state: FSMContext):
    try:
        total_balance = parse_amount(message.text, allow_zero=True)
    except ValueError:
        await handle_invalid_input(
            message, state, phrases.ERR_INVALID_NUMBER.format(example="50000")
        )
        return

    new_limit, days_left, money_for_life, mandatory, cubyshka = await reconcile_budget_with_reality(
        message.from_user.id, total_balance
    )
    await apply_reconciliation(message.from_user.id, money_for_life)
    from ...services.recovery_service import invalidate_recovery_offer_context

    try:
        await invalidate_recovery_offer_context(message.from_user.id)
    except Exception:
        pass
    await state.clear()
    await message.answer(
        text=phrases.RECALC_LIMIT_DONE.format(
            limit=int(new_limit),
            money=int(money_for_life),
            days=days_left,
        ),
        reply_markup=await get_main_menu_keyboard(message.from_user.id),
    )
    await _handle_recovery_budget_change(message.from_user.id, message)


# ============ SETTINGS ============


async def _render_settings(telegram_id: int) -> tuple[str, InlineKeyboardMarkup]:
    budget = await get_budget_or_none(telegram_id)
    if not budget:
        return phrases.NO_BUDGET_SETTINGS, await get_main_menu_keyboard(telegram_id)

    period_day = budget.period_start_day or 1
    period_info = (
        phrases.SETTINGS_PERIOD_FROM.format(day=period_day)
        if period_day != 1
        else phrases.SETTINGS_PERIOD_WHOLE
    )
    if budget.free_money > 0:
        money_line = phrases.SETTINGS_MONEY_FREE.format(amount=f"{budget.free_money:,.0f}")
    else:
        money_line = phrases.SETTINGS_MONEY_INCOME.format(amount=f"{budget.total_income:,.0f}")
    text = phrases.SETTINGS_BUDGET_TITLE.format(money=money_line, period=period_info)
    return text, get_settings_keyboard()


async def _render_advanced_planning(telegram_id: int) -> tuple[str, InlineKeyboardMarkup]:
    budget = await get_budget_or_none(telegram_id)
    if not budget:
        return phrases.NO_BUDGET_SETTINGS, await get_main_menu_keyboard(telegram_id)

    text = phrases.ADVANCED_PLANNING_TITLE.format(
        mandatory=f"{budget.mandatory_payments:,.0f}",
    )
    return text, get_advanced_planning_keyboard()


@router.callback_query(F.data == "menu_settings")
async def menu_settings(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    text, kb = await _render_settings(callback.from_user.id)
    await callback.message.edit_text(text=text, reply_markup=kb)


@router.callback_query(F.data == "menu_advanced_planning")
async def menu_advanced_planning(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    text, kb = await _render_advanced_planning(callback.from_user.id)
    await callback.message.edit_text(text=text, reply_markup=kb)


@router.callback_query(F.data == "add_income")
async def add_income(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(EditBudget.waiting_for_add_income)
    await callback.message.edit_text(
        text=phrases.INCOME_ADD_PROMPT, reply_markup=get_cancel_keyboard()
    )


@router.callback_query(F.data == "adv_mandatory")
async def adv_mandatory(callback: CallbackQuery, state: FSMContext):
    _from_advanced_planning.add(callback.from_user.id)
    await edit_mandatory(callback, state)


@router.callback_query(F.data == "adv_black_day")
async def adv_black_day(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    text, kb = await _render_advanced_planning(callback.from_user.id)
    await callback.message.edit_text(text=text, reply_markup=kb)


@router.callback_query(F.data == "adv_wishlist")
async def adv_wishlist(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    text, kb = await _render_advanced_planning(callback.from_user.id)
    await callback.message.edit_text(text=text, reply_markup=kb)


@router.callback_query(F.data == "edit_mandatory")
async def edit_mandatory(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(EditBudget.waiting_for_mandatory)
    await callback.message.edit_text(
        text=phrases.MANDATORY_EDIT_PROMPT, reply_markup=get_cancel_keyboard()
    )


@router.callback_query(F.data == "edit_black_day")
async def edit_black_day(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(EditBudget.waiting_for_black_day)
    await callback.message.edit_text(
        text=phrases.SAVINGS_EDIT_PROMPT, reply_markup=get_cancel_keyboard()
    )


@router.callback_query(F.data == "edit_wishlist")
async def edit_wishlist(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    text, kb = await _render_advanced_planning(callback.from_user.id)
    await callback.message.edit_text(text=text, reply_markup=kb)


@router.callback_query(F.data == "edit_period_start")
async def edit_period_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(EditBudget.waiting_for_period_start)
    await callback.message.edit_text(
        text=phrases.PERIOD_EDIT_PROMPT, reply_markup=get_period_start_keyboard()
    )


@router.message(EditBudget.waiting_for_period_start, F.text.in_(REPLY_MENU_COMMANDS))
async def handle_menu_interrupt_in_edit_budget(message: Message, state: FSMContext):
    await message.answer(
        phrases.FSM_INTERRUPT_PERIOD,
        reply_markup=get_cancel_keyboard(),
    )


@router.message(EditBudget.waiting_for_period_start)
async def save_edit_period_start(message: Message, state: FSMContext):
    import calendar

    today = get_msk_now()
    try:
        day = int(message.text.strip())
    except (ValueError, TypeError):
        await handle_invalid_input(message, state, phrases.ERR_INVALID_NUMBER.format(example="25"))
        return

    if day < 1:
        day = 1
    elif day > 31:
        day = 31

    days_in_month = calendar.monthrange(today.year, today.month)[1]
    if day > days_in_month:
        day = days_in_month

    await update_budget_field(message.from_user.id, "period_start_day", day)

    await message.answer(
        text=phrases.PERIOD_UPDATED.format(day=day),
        reply_markup=await get_main_menu_keyboard(message.from_user.id),
    )
    await _handle_recovery_budget_change(message.from_user.id, message)
    await state.clear()


@router.message(EditBudget.waiting_for_add_income)
async def save_add_income(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text)
    except ValueError:
        await handle_invalid_input(
            message, state, phrases.ERR_INVALID_NUMBER.format(example="10000")
        )
        return

    budget = await get_budget_or_none(message.from_user.id)
    if not budget:
        await message.answer(phrases.ERR_NO_BUDGET)
        await state.clear()
        return
    if budget.free_money > 0:
        new_total = budget.free_money + amount
        await update_budget_field(message.from_user.id, "free_money", new_total)
    else:
        new_total = budget.total_income + amount
        await update_budget_field(message.from_user.id, "total_income", new_total)

    await message.answer(
        text=phrases.INCOME_ADDED.format(amount=f"{amount:,.0f}", total=f"{new_total:,.0f}"),
        reply_markup=await get_main_menu_keyboard(message.from_user.id),
    )
    await _handle_recovery_budget_change(message.from_user.id, message)
    await state.clear()


@router.message(EditBudget.waiting_for_mandatory)
async def save_mandatory(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text, allow_zero=True)
    except ValueError:
        await handle_invalid_input(
            message, state, phrases.ERR_INVALID_NUMBER.format(example="15000")
        )
        return

    await update_budget_field(message.from_user.id, "mandatory_payments", amount)
    if message.from_user.id in _from_advanced_planning:
        _from_advanced_planning.discard(message.from_user.id)
        await state.clear()
        text, kb = await _render_advanced_planning(message.from_user.id)
        await message.answer(text=text, reply_markup=kb)
        await _handle_recovery_budget_change(message.from_user.id, message)
    else:
        await message.answer(
            text=phrases.MANDATORY_UPDATED.format(amount=f"{amount:,.0f}"),
            reply_markup=await get_main_menu_keyboard(message.from_user.id),
        )
        await _handle_recovery_budget_change(message.from_user.id, message)
        await state.clear()


@router.message(EditBudget.waiting_for_black_day)
async def save_black_day(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text, allow_zero=True)
    except ValueError:
        await handle_invalid_input(
            message, state, phrases.ERR_INVALID_NUMBER.format(example="5000")
        )
        return

    await update_budget_field(message.from_user.id, "black_day_fund", amount)
    if message.from_user.id in _from_advanced_planning:
        _from_advanced_planning.discard(message.from_user.id)
        await state.clear()
        text, kb = await _render_advanced_planning(message.from_user.id)
        await message.answer(text=text, reply_markup=kb)
        await _handle_recovery_budget_change(message.from_user.id, message)
    else:
        await message.answer(
            text=phrases.SAVINGS_UPDATED.format(amount=f"{amount:,.0f}"),
            reply_markup=await get_main_menu_keyboard(message.from_user.id),
        )
        await _handle_recovery_budget_change(message.from_user.id, message)
        await state.clear()


@router.message(EditBudget.waiting_for_wishlist)
async def save_wishlist(message: Message, state: FSMContext):
    name, price = _parse_wishlist(message.text.strip())
    name = name[:255]

    await update_budget_field(message.from_user.id, "wishlist_name", name)
    await update_budget_field(message.from_user.id, "wishlist_target", price)
    # full removal: also clear Wishlist table so status hides
    try:
        async with async_session_maker() as session:
            from sqlalchemy import select as _select

            from ...db.models.models import Wishlist as _Wishlist

            result = await session.execute(
                _select(_Wishlist).where(
                    _Wishlist.telegram_id == message.from_user.id, _Wishlist.is_active == True
                )
            )
            for w in result.scalars().all():
                w.current_amount = 0
                w.target_amount = 0
                w.is_active = False
            await session.commit()
    except Exception:
        pass

    if message.from_user.id in _from_advanced_planning:
        _from_advanced_planning.discard(message.from_user.id)
        await state.clear()
        text, kb = await _render_advanced_planning(message.from_user.id)
        await message.answer(text=text, reply_markup=kb)
    else:
        await state.clear()
        text, kb = await _render_advanced_planning(message.from_user.id)
        await message.answer(text=text, reply_markup=kb)


# ============ ROUNDING MODE SETTINGS ============


@router.callback_query(F.data == "edit_rounding")
async def edit_rounding(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    async with async_session_maker() as session:
        result = await session.execute(
            select(UserSettings).where(UserSettings.telegram_id == callback.from_user.id)
        )
        settings = result.scalar_one_or_none()
        current = settings.rounding_mode if settings else 0

    label = phrases.ROUNDING_LABEL_OFF if current == 0 else f"{current} ₽"
    await callback.message.edit_text(
        text=phrases.ROUNDING_SETTINGS.format(label=label),
        reply_markup=get_rounding_mode_keyboard(),
    )


# ============ CANCEL / BACK ============


@router.callback_query(F.data == "cancel")
async def cancel(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.edit_text(
        text=phrases.BACK_NAV,
        reply_markup=await get_main_menu_keyboard(callback.from_user.id),
    )
    if settings.EXPENSE_SIMPLE_CHECK:
        await callback.message.answer(
            text="\u200b",
            reply_markup=get_main_reply_keyboard(),
        )


# ============ DUPLICATE DETECTION CALLBACKS ============


@router.callback_query(F.data == "dup_confirm")
async def handle_duplicate_confirm(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    pending = dup_middleware.get_pending(user_id)
    if not pending:
        await callback.message.edit_text(phrases.ERR_EXPENSE_NOT_FOUND)
        return

    try:
        async with async_session_maker() as session:
            expense = Expense(
                telegram_id=user_id,
                amount=pending["amount"],
                description=pending["description"],
                category_id=pending["cat_id"],
                date=get_msk_now(),
            )
            session.add(expense)
            await session.commit()
    except Exception as e:
        logging.error("Duplicate confirm expense insert failed", exc_info=e)
        await callback.message.edit_text(phrases.ERR_EXPENSE_SAVE)
        return

    spent = await get_today_expenses_sum(user_id)
    balance = phrases.BALANCE_UNKNOWN
    try:
        budget = await get_active_budget(user_id)
        if budget:
            remaining = max(int(budget.daily_limit) - int(spent), 0)
            balance = f"{remaining:,} ₽"
    except Exception:
        pass

    response_text = phrases.DUP_CONFIRMED.format(
        amount=f"{pending['amount']:,.0f}",
        desc=safe(pending["description"]),
        balance=balance,
    )
    dup_middleware.record(
        user_id,
        0,
        pending["amount"],
        pending["description"],
        expense.id,
        response_text=response_text,
    )
    dup_middleware.reset_dup_count(user_id, pending["amount"], pending["description"])

    await callback.message.edit_text(text=response_text)


@router.callback_query(F.data == "dup_del")
async def handle_duplicate_delete(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    pending = dup_middleware.get_pending(user_id)
    if not pending:
        await callback.message.edit_text(phrases.ERR_EXPENSE_NOT_FOUND)
        return

    dup_middleware.reset_dup_count(user_id, pending["amount"], pending["description"])
    await callback.message.edit_text(
        text=phrases.DUP_DELETED.format(
            amount=f"{pending['amount']:,.0f}",
            desc=safe(pending["description"]),
        ),
    )


# ============ UNSUPPORTED CONTENT ============


@router.message(F.voice)
async def handle_voice(message: Message):
    await message.answer(phrases.ERR_VOICE)


@router.message(F.photo | F.video | F.document | F.sticker | F.animation)
async def handle_media(message: Message):
    await message.answer(phrases.ERR_MEDIA)


# ============ REPLY KEYBOARD ============

_REPLY_BTNS = {
    phrases.BTN_ADD_EXPENSE,
    phrases.BTN_DAILY_LIMIT,
    phrases.BTN_STATS,
    phrases.BTN_SETTINGS,
    phrases.BTN_HELP,
}


@router.message(F.text.in_(_REPLY_BTNS))
async def handle_reply_menu(message: Message, state: FSMContext):
    await state.clear()
    btn_text = message.text

    if btn_text == phrases.BTN_ADD_EXPENSE:
        await state.set_state(AddExpense.waiting_for_amount)
        await message.answer(
            text=phrases.ADD_EXPENSE_PROMPT,
            reply_markup=get_cancel_keyboard(),
        )
        return

    if btn_text == phrases.BTN_DAILY_LIMIT:
        text, kb = await _build_status(message.from_user.id)
        await message.answer(text=text, reply_markup=kb)
        return

    if btn_text == phrases.BTN_STATS:
        from ..keyboards import get_stats_keyboard

        await message.answer(
            text=phrases.BTN_STATS,
            reply_markup=get_stats_keyboard(),
        )
        return

    if btn_text == phrases.BTN_SETTINGS:
        text, kb = await _render_settings(message.from_user.id)
        await message.answer(text=text, reply_markup=kb)
        return

    if btn_text == phrases.BTN_HELP:
        await message.answer(
            text=phrases.HELP_TEXT,
            reply_markup=await get_main_menu_keyboard(message.from_user.id),
        )
        return


# ============ TEXT INPUT (free form) ============


@router.message()
async def handle_text(message: Message, state: FSMContext):
    text = message.text.strip()

    if text.startswith("/"):
        return

    menu_keywords = phrases.MENU_KEYWORDS
    if text.lower() in menu_keywords:
        await message.answer(
            text=phrases.UNRECOGNIZED,
            reply_markup=await get_main_menu_keyboard(message.from_user.id),
        )
        return

    result = parse_multi_expense_text(text)
    if not result.reports:
        return

    if not result.is_fully_valid:
        invalid = next((r for r in result.reports if not r.is_valid), None)
        if invalid and invalid.error_type == "MATH_ERROR":
            await message.answer(
                phrases.ERR_MATH_ERROR.format(detail=safe(invalid.error_detail or invalid.raw_text))
            )
        return

    await get_or_create_user(
        telegram_id=message.from_user.id,
        first_name=message.from_user.first_name,
        username=message.from_user.username,
    )

    user_id = message.from_user.id
    (
        sent_dup,
        all_silent,
        lines,
        first_id,
        corrected_ids,
    ) = await _save_expenses_from_parsed_list(user_id, result.reports, message)
    if sent_dup:
        return

    if all_silent:
        return

    if not lines:
        await message.answer(phrases.ERR_EXPENSE_SAVE)
        return

    kb = _build_expense_check_kb(first_id, len(lines), corrected_ids)

    response_text = phrases.EXPENSE_SAVED_ALL.format(lines="\n".join(lines), round_up="")
    await message.answer(text=response_text, reply_markup=kb)
