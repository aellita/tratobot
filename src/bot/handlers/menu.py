import logging
import random
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from ...core.config import settings
from ...db.database import async_session_maker
from ...db.models.models import Budget, Category, Expense, User, UserSettings, Wishlist
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
    compute_rounding,
    get_rounding_mode,
    get_today_expenses_sum,
    parse_multi_expense_text,
)
from ...services.goal_service import add_spare_change_to_goal, get_goal_current_amount
from ...services.user_service import get_or_create_user
from ...utils import phrases
from ...utils.helpers import get_msk_now, parse_amount, safe
from ..keyboards import (
    get_cancel_keyboard,
    get_duplicate_keyboard,
    get_main_menu_keyboard,
    get_main_reply_keyboard,
    get_onboarding_keyboard,
    get_period_start_keyboard,
    get_rounding_mode_keyboard,
    get_settings_keyboard,
    get_start_choice_keyboard,
)
from ..middleware import dup_middleware

router = Router()


class BudgetSetup(StatesGroup):
    waiting_for_income = State()
    waiting_for_period_start = State()
    waiting_for_mandatory = State()
    waiting_for_black_day = State()
    waiting_for_wishlist_name = State()
    waiting_for_rounding_mode = State()


class EditBudget(StatesGroup):
    waiting_for_income = State()
    waiting_for_add_income = State()
    waiting_for_period_start = State()
    waiting_for_mandatory = State()
    waiting_for_black_day = State()
    waiting_for_wishlist = State()


class AddExpense(StatesGroup):
    waiting_for_amount = State()


class CustomCategory(StatesGroup):
    waiting_for_name = State()


class CriticalReset(StatesGroup):
    waiting_for_real_balance = State()


class FreshStart(StatesGroup):
    waiting_for_mandatory = State()
    waiting_for_black_day = State()
    waiting_for_balance = State()


async def get_user_or_none(telegram_id: int) -> User | None:
    async with async_session_maker() as session:
        return await session.get(User, telegram_id)


async def get_budget_or_none(telegram_id: int) -> Budget | None:
    from ...services.budget_service import get_active_budget

    return await get_active_budget(telegram_id)


def _build_expense_check_kb(first_id: int | None, line_count: int) -> InlineKeyboardMarkup | None:
    if not settings.EXPENSE_SIMPLE_CHECK:
        if line_count == 1:
            return InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=phrases.BTN_CHANGE_CATEGORY,
                            callback_data=f"change_cat:{first_id}",
                        )
                    ],
                    [InlineKeyboardButton(text=phrases.BTN_BACK_MAIN, callback_data="menu_back")],
                ]
            )
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=phrases.BTN_BACK_MAIN, callback_data="menu_back")],
            ]
        )
    if line_count == 1 and first_id:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=phrases.BTN_CHANGE_CATEGORY,
                        callback_data=f"change_cat:{first_id}",
                    )
                ],
            ]
        )
    return None


# ============ MENU HANDLERS ============


@router.callback_query(F.data == "menu_back")
async def menu_back(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if settings.EXPENSE_SIMPLE_CHECK:
        return
    await state.clear()
    user_name = callback.from_user.first_name or phrases.FALLBACK_NAME
    await callback.message.edit_text(
        text=phrases.BACK_NAV.format(name=user_name),
        reply_markup=await get_main_menu_keyboard(callback.from_user.id),
    )


@router.callback_query(F.data == "menu_help")
async def menu_help(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    user_name = callback.from_user.first_name or phrases.FALLBACK_NAME
    await callback.message.edit_text(
        text=phrases.HELP_TEXT.format(name=user_name),
        reply_markup=await get_main_menu_keyboard(callback.from_user.id),
    )


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    telegram_id = message.from_user.id
    user_name = message.from_user.first_name or phrases.FALLBACK_NAME

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

        await message.answer(text=phrases.ONBOARDING_START, reply_markup=get_onboarding_keyboard())
        await state.set_state(BudgetSetup.waiting_for_income)
    else:
        await message.answer(
            text=phrases.WELCOME_BACK.format(name=user_name),
            reply_markup=get_start_choice_keyboard(),
        )
        if settings.EXPENSE_SIMPLE_CHECK:
            await message.answer(
                text=phrases.WELCOME_MENU.format(name=user_name),
                reply_markup=get_main_reply_keyboard(),
            )


@router.callback_query(F.data == "open_menu")
async def open_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if settings.EXPENSE_SIMPLE_CHECK:
        return
    await state.clear()
    user_name = callback.from_user.first_name or phrases.FALLBACK_NAME
    await callback.message.edit_text(
        text=phrases.BACK_NAV.format(name=user_name),
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


@router.callback_query(F.data == "menu_status")
async def menu_status(callback: CallbackQuery):
    await callback.answer()
    text, kb = await _build_status(callback.from_user.id)
    await callback.message.edit_text(text=text, reply_markup=kb)


async def _build_status(telegram_id: int) -> tuple[str, InlineKeyboardMarkup]:
    user_name = "user"
    tg_id = telegram_id

    budget = await get_budget_or_none(tg_id)
    if not budget:
        return phrases.NO_BUDGET.format(name=user_name), await get_main_menu_keyboard(tg_id)

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

        result = await session.execute(
            select(func.sum(Expense.amount)).where(
                Expense.telegram_id == tg_id,
                Expense.is_deleted == False,
            )
        )
        spent_period = result.scalar() or 0

    days_left = budget.days_remaining
    dl_base = budget.daily_limit
    savings = budget.black_day_fund

    if budget.free_money > 0:
        money_for_life = budget.free_money - spent_period
    else:
        money_for_life = (
            budget.total_income - budget.mandatory_payments - budget.black_day_fund - spent_period
        )

    dl_pred = max(money_for_life / max(days_left, 1), 0) if money_for_life > 0 else 0
    dl_simulated = max((money_for_life + savings) / max(days_left, 1), 0)
    pct_pred = dl_pred / max(dl_base, 1) * 100 if dl_base > 0 else 0
    pct_sim = dl_simulated / max(dl_base, 1) * 100 if dl_base > 0 else 0

    remaining_today = max(dl_base - spent_today, 0)
    remaining_period = money_for_life
    period_end_day = budget.period_start_day or 1
    period_end_str = f"{period_end_day}-го" if period_end_day > 1 else f"{period_end_day}-го"

    end_of_period = days_left <= 3

    if end_of_period and money_for_life <= 0:
        zone_emoji = "🔴"
        zone_label = "Атас"
    elif end_of_period:
        zone_emoji = "🟢"
        zone_label = "Финиш"
    elif pct_pred > 80:
        zone_emoji = "🟢"
        zone_label = "В лимите"
    elif pct_pred >= 51:
        zone_emoji = "🔵"
        zone_label = "Можно больше"
    elif pct_pred >= 26:
        zone_emoji = "🟡"
        zone_label = "На грани"
    else:
        zone_emoji = "🔴"
        zone_label = "Критично"

    wishlist_amount = await get_goal_current_amount(tg_id)

    if remaining_today > 0:
        today_line = f"Свободно {int(remaining_today):,} ₽"
    else:
        today_line = "Свободно 0 ₽ ⛔"

    spent_line = f"Потрачено {int(spent_today):,} ₽"
    if spent_today > dl_base:
        spent_line += " ⚠️"

    text = (
        f"<b>БАЛАНС</b> · {zone_emoji} {zone_label}\n\n"
        f"<b>Сегодня</b>\n"
        f"{today_line} · {spent_line}\n\n"
        f"<b>Период (до {period_end_str} · {days_left} дн.)</b>\n"
        f"Остаток {int(remaining_period):,} ₽ · Лимит {int(dl_base):,} ₽/день\n\n"
        f"<b>Резервы под охраной</b>\n"
        f"Обязательные {int(budget.mandatory_payments):,} · "
        f"Кубышка {int(savings):,} · "
        f"Хотелка {int(wishlist_amount):,}"
    )

    footer = ""
    if end_of_period:
        if money_for_life <= 0:
            footer = random.choice(
                [
                    "Финишная прямая! Кошелёк пуст. Держимся на морально-волевых, без новых долгов!",
                    "До конца периода пара дней, а мы на нуле. Терпим, финиш уже виден!",
                    "Последние метры, денег нет. Но мы доползём без кредитов!",
                ]
            )
            btns = "FRESH_START"
        else:
            footer = random.choice(
                [
                    "Осталось пару дней, а у нас ещё есть кэш! Досрочная победа!",
                    "Финишная прямая, в кармане шуршат купюры! Горжусь дисциплиной!",
                    "Период почти закрыт, бюджет не пробит! Абсолютная победа!",
                ]
            )
            btns = "REGULAR"
    elif pct_pred > 80:
        footer = random.choice(
            [
                f"Идём идеально по графику! Прогнозный лимит: {int(dl_pred):,} ₽/день. Жаба спокойна!",
                "Всё пучком. Лимит комфортный. Продолжай в том же духе!",
                "Финансовая карма в порядке. Можно позволить себе чуточку больше!",
            ]
        )
        btns = "REGULAR"
    elif pct_pred >= 51:
        footer = random.choice(
            [
                f"Заметил, мы ускорились. Лимит сожмётся до {int(dl_pred):,} ₽. Притормози?",
                f"Съезжаем с курса. Прогноз {int(dl_pred):,} ₽/день. Включи осознанность.",
                f"График пополз вниз. Прогноз {int(dl_pred):,} ₽/день — удержим планку?",
            ]
        )
        btns = "REGULAR"
    elif pct_pred >= 26:
        if pct_sim > 80:
            footer = f"Кубышка ({int(savings):,}₽) вернёт в зелень — {int(dl_simulated):,}₽/день"
            btns = "FROM_YELLOW_TO_GREEN"
        elif pct_sim >= 51:
            footer = f"Кубышка подстрахует — {int(dl_simulated):,}₽/день"
            btns = "FROM_YELLOW_TO_BLUE"
        else:
            footer = random.choice(
                [
                    f"Лимит сожмётся до {int(dl_pred):,} ₽/день. Режим супер-экономии.",
                    f"Прогноз {int(dl_pred):,} ₽/день. Постарайся сегодня ничего не покупать!",
                    f"До конца периода — гречка. Лимит {int(dl_pred):,} ₽/день. Держимся!",
                ]
            )
            btns = "REGULAR"
    else:
        if pct_sim > 80:
            footer = f"Кубышка ({int(savings):,}₽) вернёт в зелень — {int(dl_simulated):,}₽/день"
            btns = "FROM_RED_TO_GREEN"
        elif pct_sim >= 51:
            footer = f"Кубышка смягчит до {int(dl_simulated):,}₽/день"
            btns = "FROM_RED_TO_BLUE"
        elif pct_sim >= 26:
            footer = f"Кубышка поднимет до {int(dl_simulated):,}₽/день"
            btns = "FROM_RED_TO_YELLOW"
        else:
            footer = random.choice(
                [
                    "Пробили дно! Деньги кончились. Пора пересобрать бюджет.",
                    "Дальше ехать некуда. Давай начнём с чистого листа?",
                    "Математика не бьётся с картой. Пора обнулить месяц!",
                ]
            )
            btns = "FRESH_START"

    kb = _build_status_keyboard(btns, tg_id)
    return text + "\n\n" + footer if footer else text, kb


def _build_status_keyboard(btn_type: str, tg_id: int) -> InlineKeyboardMarkup:
    if settings.EXPENSE_SIMPLE_CHECK:
        if btn_type == "REGULAR":
            return InlineKeyboardMarkup(inline_keyboard=[])
        if btn_type == "FRESH_START":
            return InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=phrases.BTN_FRESH_START, callback_data="trigger_critical_reset"
                        )
                    ],
                ]
            )
        if btn_type in ("FROM_YELLOW_TO_GREEN", "FROM_YELLOW_TO_BLUE"):
            label = (
                phrases.BTN_USE_SAVINGS_COMFORT
                if btn_type == "FROM_YELLOW_TO_GREEN"
                else phrases.BTN_RAISE_LIMIT_SAVINGS
            )
            return InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=label, callback_data="use_savings")],
                ]
            )
        if btn_type in ("FROM_RED_TO_GREEN", "FROM_RED_TO_BLUE", "FROM_RED_TO_YELLOW"):
            return InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text={
                                "FROM_RED_TO_GREEN": phrases.BTN_RESTORE_GREEN_SAVINGS,
                                "FROM_RED_TO_BLUE": phrases.BTN_EXIT_CRISIS_GREEN,
                                "FROM_RED_TO_YELLOW": phrases.BTN_SAVE_BUDGET_SAVINGS,
                            }[btn_type],
                            callback_data="use_savings",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text=phrases.BTN_FROM_SLATE, callback_data="trigger_critical_reset"
                        )
                    ],
                ]
            )
        return InlineKeyboardMarkup(inline_keyboard=[])

    if btn_type == "REGULAR":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=phrases.BTN_BACK_MAIN, callback_data="menu_back")],
            ]
        )
    if btn_type == "FRESH_START":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=phrases.BTN_FRESH_START, callback_data="trigger_critical_reset"
                    )
                ],
                [InlineKeyboardButton(text=phrases.BTN_BACK_MAIN, callback_data="menu_back")],
            ]
        )
    if btn_type == "FROM_YELLOW_TO_GREEN":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=phrases.BTN_USE_SAVINGS_COMFORT, callback_data="use_savings"
                    )
                ],
                [InlineKeyboardButton(text=phrases.BTN_ECONOMIZE, callback_data="menu_back")],
            ]
        )
    if btn_type == "FROM_YELLOW_TO_BLUE":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=phrases.BTN_RAISE_LIMIT_SAVINGS, callback_data="use_savings"
                    )
                ],
                [InlineKeyboardButton(text=phrases.BTN_ECONOMIZE, callback_data="menu_back")],
            ]
        )
    if btn_type == "FROM_RED_TO_GREEN":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=phrases.BTN_RESTORE_GREEN_SAVINGS, callback_data="use_savings"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=phrases.BTN_FROM_SLATE, callback_data="trigger_critical_reset"
                    )
                ],
                [InlineKeyboardButton(text=phrases.BTN_BACK_MAIN, callback_data="menu_back")],
            ]
        )
    if btn_type == "FROM_RED_TO_BLUE":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=phrases.BTN_EXIT_CRISIS_GREEN, callback_data="use_savings"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=phrases.BTN_FROM_SLATE, callback_data="trigger_critical_reset"
                    )
                ],
                [InlineKeyboardButton(text=phrases.BTN_BACK_MAIN, callback_data="menu_back")],
            ]
        )
    if btn_type == "FROM_RED_TO_YELLOW":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=phrases.BTN_SAVE_BUDGET_SAVINGS, callback_data="use_savings"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=phrases.BTN_FROM_SLATE, callback_data="trigger_critical_reset"
                    )
                ],
                [InlineKeyboardButton(text=phrases.BTN_BACK_MAIN, callback_data="menu_back")],
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=phrases.BTN_BACK_MAIN, callback_data="menu_back")],
        ]
    )


@router.callback_query(F.data == "use_savings")
async def handle_use_savings(callback: CallbackQuery):
    await callback.answer()
    tg_id = callback.from_user.id
    async with async_session_maker() as session:
        month = get_msk_now().strftime("%Y-%m")
        result = await session.execute(
            select(Budget).where(Budget.telegram_id == tg_id, Budget.month == month)
        )
        budget = result.scalar_one_or_none()
        if not budget or budget.black_day_fund <= 0:
            await callback.message.edit_text(
                text=phrases.ERR_SAVINGS_EMPTY,
                reply_markup=await get_main_menu_keyboard(tg_id),
            )
            return
        budget.free_money = (budget.free_money or 0) + budget.black_day_fund
        budget.black_day_fund = 0
        await session.commit()
    await menu_status(callback)


# ============ ONBOARDING / SKIP ============


@router.callback_query(F.data == "skip_step")
async def skip_step(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    current_state = await state.get_state()

    if current_state == BudgetSetup.waiting_for_income.state:
        await state.update_data(
            income=0, mandatory=0, black_day=0, wishlist_name="", wishlist_price=0
        )
        await _finish_onboarding(callback, state)
    elif current_state == BudgetSetup.waiting_for_period_start.state:
        await state.update_data(period_start_day=1)
        await _advance_onboarding(callback, state)
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
        days_remaining = max(days_in_month - today.day, 0)
    elif today.day >= clamped_start:
        remaining_this = days_in_month - today.day
        days_remaining = remaining_this + clamped_start - 1
    else:
        days_remaining = clamped_start - today.day
    daily_limit = max(available / max(days_remaining, 1), 0)

    user_name = source.from_user.first_name or phrases.FALLBACK_NAME

    period_note = f"📅 Период: с {period_start_day}-го числа\n" if period_start_day != 1 else ""
    text = phrases.BUDGET_COMPLETE.format(
        name=user_name,
        month=month,
        income=f"{data.get('income', 0):,.0f}",
        mandatory=f"{data.get('mandatory', 0):,.0f}",
        black_day=f"{data.get('black_day', 0):,.0f}",
        wishlist=f"{wishlist_price:,.0f}",
        period_note=period_note,
        daily_limit=f"{daily_limit:,.0f}",
    )

    kb = await get_main_menu_keyboard(telegram_id)
    if isinstance(source, CallbackQuery):
        await source.message.edit_text(text=text, reply_markup=kb)
    else:
        await source.answer(text=text, reply_markup=kb)

    if settings.EXPENSE_SIMPLE_CHECK:
        user_name = source.from_user.first_name or phrases.FALLBACK_NAME
        if isinstance(source, CallbackQuery):
            await source.message.answer(
                text=phrases.WELCOME_MENU.format(name=user_name),
                reply_markup=get_main_reply_keyboard(),
            )
        else:
            await source.answer(
                text=phrases.WELCOME_MENU.format(name=user_name),
                reply_markup=get_main_reply_keyboard(),
            )

    await state.clear()


# ============ BUDGET SETUP STEPS ============


@router.message(BudgetSetup.waiting_for_income)
async def process_income(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text)
    except ValueError:
        await message.answer(phrases.ERR_INVALID_NUMBER.format(example="50000"))
        return

    await state.update_data(income=amount)
    await state.set_state(BudgetSetup.waiting_for_period_start)
    await message.answer(
        text=f"✅ Принял!\n\n{phrases.PERIOD_START_CHOICE}",
        reply_markup=get_period_start_keyboard(),
    )


@router.callback_query(F.data.in_(["period_today", "period_first", "period_other"]))
async def handle_period_start_choice(callback: CallbackQuery, state: FSMContext):
    import calendar

    today = get_msk_now()
    current_state = await state.get_state()

    if callback.data == "period_other":
        await callback.message.edit_text(text=phrases.PERIOD_CUSTOM_PROMPT, reply_markup=None)
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
        await state.set_state(BudgetSetup.waiting_for_mandatory)
        await callback.message.edit_text(
            text=phrases.INCOME_SAVED_PERIOD, reply_markup=get_onboarding_keyboard()
        )
    elif current_state == EditBudget.waiting_for_period_start.state:
        await update_budget_field(callback.from_user.id, "period_start_day", day)
        user_name = callback.from_user.first_name or phrases.FALLBACK_NAME
        await callback.message.edit_text(
            text=phrases.PERIOD_UPDATED.format(name=user_name, day=day),
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )
        await state.clear()

    await callback.answer()


@router.message(BudgetSetup.waiting_for_period_start)
async def process_period_start(message: Message, state: FSMContext):
    import calendar

    today = get_msk_now()
    try:
        day = int(message.text.strip())
    except (ValueError, TypeError):
        data = await state.get_data()
        retries = data.get("_retry_count", 0) + 1
        await state.update_data(_retry_count=retries)
        if retries >= 3:
            await state.clear()
            await message.answer(
                phrases.ERR_TOO_MANY_RETRIES,
                reply_markup=await get_main_menu_keyboard(message.from_user.id),
            )
            return
        await message.answer(phrases.ERR_INVALID_NUMBER.format(example="25"))
        return

    if day < 1:
        day = 1
    elif day > 31:
        day = 31

    days_in_month = calendar.monthrange(today.year, today.month)[1]
    if day > days_in_month:
        day = days_in_month

    await state.update_data(period_start_day=day)
    await state.set_state(BudgetSetup.waiting_for_mandatory)
    await message.answer(text=phrases.INCOME_SAVED_PERIOD, reply_markup=get_onboarding_keyboard())


@router.message(BudgetSetup.waiting_for_mandatory)
async def process_mandatory(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text, allow_zero=True)
    except (ValueError, TypeError):
        await message.answer(phrases.ERR_INVALID_NUMBER.format(example="15000"))
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
        await message.answer(phrases.ERR_INVALID_NUMBER.format(example="5000"))
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
    user_name = callback.from_user.first_name or phrases.FALLBACK_NAME
    label = phrases.ROUNDING_LABEL_OFF if mode == 0 else f"{mode} ₽"
    await callback.message.edit_text(
        text=phrases.ROUNDING_SAVED.format(name=user_name, label=label),
        reply_markup=await get_main_menu_keyboard(callback.from_user.id),
    )


# ============ ADD EXPENSE ============


@router.callback_query(F.data == "menu_add")
async def menu_add(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_name = callback.from_user.first_name or phrases.FALLBACK_NAME
    await state.set_state(AddExpense.waiting_for_amount)
    await callback.message.edit_text(
        text=phrases.ADD_EXPENSE_PROMPT.format(name=user_name), reply_markup=get_cancel_keyboard()
    )


async def _save_expenses_from_parsed_list(
    user_id: int,
    parsed_list: list[tuple[float, str]],
    message: Message,
) -> tuple[bool, bool, list[str], float, int | None]:
    rounding_mode = await get_rounding_mode(user_id)
    lines = []
    total_spare = 0.0
    first_id = None
    errors = 0
    all_silent = True

    for amount, description in parsed_list:
        if not description:
            description = phrases.FALLBACK_DESC

        effective = amount
        if rounding_mode > 0:
            effective, spare = compute_rounding(amount, rounding_mode)
            total_spare += spare

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
            return True, True, [], 0.0, None

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
        dup_middleware.record(
            user_id, message.message_id, effective, description, expense.id,
            response_text=line,
        )
        lines.append(line)

    return False, all_silent, lines, total_spare, first_id


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

    parsed_list = parse_multi_expense_text(text)
    if not parsed_list:
        data = await state.get_data()
        retries = data.get("_retry_count", 0) + 1
        await state.update_data(_retry_count=retries)
        if retries >= 3:
            await state.clear()
            await message.answer(
                phrases.ERR_TOO_MANY_RETRIES,
                reply_markup=await get_main_menu_keyboard(message.from_user.id),
            )
            return
        await message.answer(phrases.ERR_INVALID_NUMBER.format(example="500 кофе"))
        return

    user_id = message.from_user.id

    if len(parsed_list) == 1:
        amount, description = parsed_list[0]
        dup_status = dup_middleware.check(user_id, amount, description)
        if dup_status != "new":
            if dup_status == "silent":
                await state.clear()
                return
            if description == phrases.FALLBACK_DESC:
                cat = None
            else:
                try:
                    cat, _ = await detect_category_db(description, user_id, amount)
                except Exception as e:
                    logging.error("Category detection failed", exc_info=e)
                    cat = None
            cat_id = cat.id if cat else None
            emoji, cat_name = get_category_display(cat.name) if cat else phrases.DEFAULT_CATEGORY
            dup_middleware.set_pending(
                user_id, amount, description, cat_id, description, emoji, cat_name
            )
            await message.answer(
                phrases.DUP_WARNING.format(amount=f"{amount:,.0f}", desc=safe(description)),
                reply_markup=get_duplicate_keyboard(),
            )
            return

    sent_dup, all_silent, lines, total_spare, first_id = await _save_expenses_from_parsed_list(
        user_id, parsed_list, message
    )
    if sent_dup:
        return

    if all_silent:
        return

    if not lines:
        await message.answer(phrases.ERR_EXPENSE_SAVE)
        return

    user_name = safe(message.from_user.first_name or phrases.FALLBACK_NAME)

    total_round_up = ""
    if total_spare > 0:
        new_total, goal_name = await add_spare_change_to_goal(user_id, total_spare)
        total_round_up = phrases.ROUND_UP.format(
            amount=int(total_spare), goal=goal_name, total=int(new_total)
        )

    kb = _build_expense_check_kb(first_id, len(lines))

    response_text = phrases.EXPENSE_SAVED_ALL.format(
        name=user_name, lines="\n".join(lines), round_up=total_round_up
    )
    await message.answer(text=response_text, reply_markup=kb)

    if settings.EXPENSE_SIMPLE_CHECK:
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
                (Category.telegram_id == callback.from_user.id) | (Category.telegram_id == None),
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
    user_name = callback.from_user.first_name or phrases.FALLBACK_NAME
    await callback.message.edit_text(
        text=phrases.BACK_NAV.format(name=user_name),
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
    name = message.text.strip().capitalize()
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

    user_name = message.from_user.first_name or phrases.FALLBACK_NAME
    await state.clear()
    await message.answer(
        text=phrases.CATEGORY_CREATED.format(
            name=name, user_name=user_name, desc=expense.description
        ),
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
        user_name = callback.from_user.first_name or phrases.FALLBACK_NAME
        await callback.message.edit_text(
            text=phrases.REDUCE_LIMIT_ACCEPTED.format(name=user_name),
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
        budget = await get_budget_or_none(callback.from_user.id)
        if budget and budget.black_day_fund > 0:
            new_fund = max(budget.black_day_fund - overdraft, 0)
            await update_budget_field(callback.from_user.id, "black_day_fund", new_fund)
            text = phrases.TAKEN_FROM_SAVINGS.format(amount=int(new_fund))
        else:
            text = phrases.ERR_SAVINGS_EMPTY
        await callback.message.edit_text(
            text=text, reply_markup=await get_main_menu_keyboard(callback.from_user.id)
        )


@router.callback_query(F.data == "trigger_critical_reset")
async def trigger_critical_reset(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(CriticalReset.waiting_for_real_balance)
    await callback.message.answer(
        text=phrases.FRESH_START_PROMPT,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=phrases.BTN_CANCEL, callback_data="cancel")],
            ]
        ),
    )


@router.message(CriticalReset.waiting_for_real_balance)
async def save_real_balance(message: Message, state: FSMContext):
    try:
        total_balance = parse_amount(message.text, allow_zero=True)
    except ValueError:
        await message.answer(phrases.ERR_INVALID_NUMBER.format(example="50000"))
        return

    user_name = message.from_user.first_name or phrases.FALLBACK_NAME
    new_limit, days_left, money_for_life, mandatory, cubyshka = await reconcile_budget_with_reality(
        message.from_user.id, total_balance
    )

    # 🟢 Зона 1: Всё ок (лимит > 500₽)
    if new_limit > 500:
        await apply_reconciliation(message.from_user.id, money_for_life)
        cubyshka_note = phrases.CUBYSHKA_NOTE.format(amount=int(cubyshka)) if cubyshka > 0 else ""
        await state.clear()
        await message.answer(
            text=phrases.FRESH_START_GREEN.format(
                name=user_name,
                limit=int(new_limit),
                days=days_left,
                money=int(money_for_life),
                note=cubyshka_note,
            ),
            reply_markup=await get_main_menu_keyboard(message.from_user.id),
        )
        return

    # 🟡 Зона 2: Турбо-экономия (лимит 100–500₽)
    if new_limit >= 100:
        await apply_reconciliation(message.from_user.id, money_for_life)
        await state.clear()
        yellow_buttons = [
            [
                InlineKeyboardButton(
                    text=phrases.BTN_TAKE_FROM_SAVINGS, callback_data="edit_black_day"
                )
            ],
        ]
        if not settings.EXPENSE_SIMPLE_CHECK:
            yellow_buttons.insert(
                0,
                [
                    InlineKeyboardButton(
                        text=phrases.BTN_ACCEPT_CHALLENGE, callback_data="menu_back"
                    )
                ],
            )
        await message.answer(
            text=phrases.FRESH_START_YELLOW.format(
                name=user_name,
                cubyshka=int(cubyshka),
                mandatory=int(mandatory),
                money=int(money_for_life),
                limit=int(new_limit),
            ),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=yellow_buttons),
        )
        return

    # 🔴 Зона 3: Тотальный фреш-старт (лимит < 100₽ или в минусе)
    await state.set_state(FreshStart.waiting_for_mandatory)
    await message.answer(
        text=phrases.FRESH_START_RED,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=phrases.BTN_RESET_ALL, callback_data="fresh_start_begin"
                    )
                ],
                [InlineKeyboardButton(text=phrases.BTN_CANCEL, callback_data="cancel")],
            ]
        ),
    )


# ============ FRESH START (RE-ONBOARDING) ============


@router.callback_query(F.data == "fresh_start_begin")
async def fresh_start_step1(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(FreshStart.waiting_for_mandatory)
    await callback.message.edit_text(
        text="📌 <b>Шаг 1.</b> Давай пересчитаем твои обязательные платежи "
        "(аренда, кредиты, подписки) с сегодняшнего дня и до конца периода.\n\n"
        "Сколько тебе <b>ЕЩЁ</b> предстоит обязательно заплатить "
        "в этом месяце?\n"
        "Если всё уже оплачено, просто напиши <b>0</b>.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=phrases.BTN_CANCEL, callback_data="cancel")],
            ]
        ),
    )


@router.message(FreshStart.waiting_for_mandatory)
async def fresh_start_save_mandatory(message: Message, state: FSMContext):
    try:
        mandatory = parse_amount(message.text, allow_zero=True)
    except ValueError:
        await message.answer(phrases.ERR_INVALID_NUMBER.format(example="15000"))
        return
    await state.update_data(fresh_mandatory=mandatory)
    await state.set_state(FreshStart.waiting_for_black_day)
    await message.answer(
        text="🏦 <b>Шаг 2.</b> Что делаем с Кубышкой?\n\n"
        "Сколько денег ты РЕАЛЬНО готова откладывать "
        "и неприкосновенно хранить прямо сейчас?\n"
        "Если пока нечего — напиши <b>0</b>, "
        "это нормально, сначала выберемся из кризиса.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=phrases.BTN_CANCEL, callback_data="cancel")],
            ]
        ),
    )


@router.message(FreshStart.waiting_for_black_day)
async def fresh_start_save_black_day(message: Message, state: FSMContext):
    try:
        cubyshka = parse_amount(message.text, allow_zero=True)
    except ValueError:
        await message.answer(phrases.ERR_INVALID_NUMBER.format(example="5000"))
        return
    await state.update_data(fresh_black_day=cubyshka)
    await state.set_state(FreshStart.waiting_for_balance)
    await message.answer(
        text="💰 <b>Шаг 3.</b> И финальный шаг.\n\n"
        "Какая <b>ОБЩАЯ</b> сумма прямо сейчас лежит "
        "на твоей карте? (Какую видишь в приложении банка).",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=phrases.BTN_CANCEL, callback_data="cancel")],
            ]
        ),
    )


@router.message(FreshStart.waiting_for_balance)
async def fresh_start_save_balance(message: Message, state: FSMContext):
    try:
        total_balance = parse_amount(message.text, allow_zero=True)
    except ValueError:
        await message.answer(phrases.ERR_INVALID_NUMBER.format(example="50000"))
        return

    data = await state.get_data()
    new_mandatory = data.get("fresh_mandatory", 0)
    new_cubyshka = data.get("fresh_black_day", 0)

    money_for_life = max(total_balance - new_mandatory - new_cubyshka, 0)
    days_left_budget = await get_budget_or_none(message.from_user.id)
    days_left = days_left_budget.days_remaining if days_left_budget else 1
    if days_left <= 0:
        days_left = 1
    new_limit = max(money_for_life / days_left, 0)

    await apply_reconciliation(
        message.from_user.id,
        free_money=money_for_life,
        new_mandatory=new_mandatory,
        new_black_day=new_cubyshka,
    )

    user_name = message.from_user.first_name or phrases.FALLBACK_NAME
    await state.clear()

    zone_note = ""
    if new_limit < 100:
        zone_note = "\n\n⚠️ Режим Турбо-экономии включён автоматически — лимит меньше 100₽."
    elif new_limit <= 500:
        zone_note = "\n\n💪 Режим Турбо-экономии включён — лимит меньше 500₽."

    await message.answer(
        text=f"Идеально, {user_name}! Новые настройки применились.\n\n"
        f"📌 {int(new_mandatory)} ₽ — забронировал на оставшиеся обязательные платежи.\n"
        f"🏦 {int(new_cubyshka)} ₽ — упаковал обратно в твою Кубышку.\n"
        f"📊 На жизнь осталось: <b>{int(money_for_life)} ₽</b>.\n"
        f"💰 Твой новый честный лимит на сегодня: <b>{int(new_limit)} ₽</b>."
        f"{zone_note}\n\n"
        f"Держимся, Бро! В этот раз мы справимся! ✊",
        reply_markup=await get_main_menu_keyboard(message.from_user.id),
    )


# ============ SETTINGS ============


@router.callback_query(F.data == "menu_settings")
async def menu_settings(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    user_name = callback.from_user.first_name or phrases.FALLBACK_NAME

    budget = await get_budget_or_none(callback.from_user.id)
    if not budget:
        await callback.message.edit_text(
            text=phrases.NO_BUDGET_SETTINGS.format(name=user_name),
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )
        return

    period_day = budget.period_start_day or 1
    period_info = f"📅 Период: с {period_day}-го" if period_day != 1 else "📅 Период: весь месяц"
    async with async_session_maker() as session:
        settings_result = await session.execute(
            select(UserSettings).where(UserSettings.telegram_id == callback.from_user.id)
        )
        user_settings = settings_result.scalar_one_or_none()
        rounding_label = (
            f"{user_settings.rounding_mode} ₽"
            if (user_settings and user_settings.rounding_mode > 0)
            else "выкл"
        )
    if budget.free_money > 0:
        money_line = f"• Свободных: {budget.free_money:,.0f}₽"
    else:
        money_line = f"• Всего доход: {budget.total_income:,.0f}₽"
    await callback.message.edit_text(
        text=f"⚙️ {user_name}, что меняем?\n\n"
        f"📊 Текущий бюджет:\n"
        f"{money_line}\n"
        f"• Обязательные: {budget.mandatory_payments:,.0f}₽\n"
        f"• Кубышка: {budget.black_day_fund:,.0f}₽\n"
        f"• {safe(budget.wishlist_name or phrases.DEFAULT_WISHLIST_NAME)}: {budget.wishlist_target:,.0f}₽\n"
        f"• Округление: {rounding_label}\n"
        f"{period_info}",
        reply_markup=get_settings_keyboard(),
    )


@router.callback_query(F.data == "edit_income")
async def edit_income(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(EditBudget.waiting_for_income)
    await callback.message.edit_text(
        text=phrases.INCOME_EDIT_PROMPT, reply_markup=get_cancel_keyboard()
    )


@router.callback_query(F.data == "add_income")
async def add_income(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(EditBudget.waiting_for_add_income)
    await callback.message.edit_text(
        text=phrases.INCOME_ADD_PROMPT, reply_markup=get_cancel_keyboard()
    )


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
    await state.set_state(EditBudget.waiting_for_wishlist)
    await callback.message.edit_text(
        text=phrases.WISHLIST_EDIT_PROMPT, reply_markup=get_cancel_keyboard()
    )


@router.callback_query(F.data == "edit_period_start")
async def edit_period_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(EditBudget.waiting_for_period_start)
    await callback.message.edit_text(
        text=phrases.PERIOD_EDIT_PROMPT, reply_markup=get_period_start_keyboard()
    )


@router.message(EditBudget.waiting_for_income)
async def save_income(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text)
        budget = await get_budget_or_none(message.from_user.id)
        if budget and budget.free_money > 0:
            await update_budget_field(message.from_user.id, "free_money", amount)
        else:
            await update_budget_field(message.from_user.id, "total_income", amount)

        await message.answer(text=phrases.INCOME_UPDATED, reply_markup=get_period_start_keyboard())
        await state.set_state(EditBudget.waiting_for_period_start)
    except ValueError:
        await message.answer(phrases.ERR_INVALID_NUMBER.format(example="50000"))


@router.message(EditBudget.waiting_for_period_start)
async def save_edit_period_start(message: Message, state: FSMContext):
    import calendar

    today = get_msk_now()
    try:
        day = int(message.text.strip())
    except (ValueError, TypeError):
        await message.answer(phrases.ERR_INVALID_NUMBER.format(example="25"))
        return

    if day < 1:
        day = 1
    elif day > 31:
        day = 31

    days_in_month = calendar.monthrange(today.year, today.month)[1]
    if day > days_in_month:
        day = days_in_month

    await update_budget_field(message.from_user.id, "period_start_day", day)
    user_name = message.from_user.first_name or phrases.FALLBACK_NAME

    await message.answer(
        text=phrases.PERIOD_UPDATED.format(name=user_name, day=day),
        reply_markup=await get_main_menu_keyboard(message.from_user.id),
    )
    await state.clear()


@router.message(EditBudget.waiting_for_add_income)
async def save_add_income(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text)
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
        user_name = message.from_user.first_name or phrases.FALLBACK_NAME

        await message.answer(
            text=phrases.INCOME_ADDED.format(
                name=user_name, amount=f"{amount:,.0f}", total=f"{new_total:,.0f}"
            ),
            reply_markup=await get_main_menu_keyboard(message.from_user.id),
        )
        await state.clear()
    except ValueError:
        await message.answer(phrases.ERR_INVALID_NUMBER.format(example="10000"))


@router.message(EditBudget.waiting_for_mandatory)
async def save_mandatory(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text, allow_zero=True)
        await update_budget_field(message.from_user.id, "mandatory_payments", amount)
        user_name = message.from_user.first_name or phrases.FALLBACK_NAME

        await message.answer(
            text=phrases.MANDATORY_UPDATED.format(name=user_name, amount=f"{amount:,.0f}"),
            reply_markup=await get_main_menu_keyboard(message.from_user.id),
        )
        await state.clear()
    except ValueError:
        await message.answer(phrases.ERR_INVALID_NUMBER.format(example="15000"))


@router.message(EditBudget.waiting_for_black_day)
async def save_black_day(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text, allow_zero=True)
        await update_budget_field(message.from_user.id, "black_day_fund", amount)
        user_name = message.from_user.first_name or phrases.FALLBACK_NAME

        await message.answer(
            text=phrases.SAVINGS_UPDATED.format(name=user_name, amount=f"{amount:,.0f}"),
            reply_markup=await get_main_menu_keyboard(message.from_user.id),
        )
        await state.clear()
    except ValueError:
        await message.answer(phrases.ERR_INVALID_NUMBER.format(example="5000"))


@router.message(EditBudget.waiting_for_wishlist)
async def save_wishlist(message: Message, state: FSMContext):
    name, price = _parse_wishlist(message.text.strip())
    name = name[:255]

    await update_budget_field(message.from_user.id, "wishlist_name", name)
    await update_budget_field(message.from_user.id, "wishlist_target", price)

    user_name = message.from_user.first_name or phrases.FALLBACK_NAME

    await message.answer(
        text=f"✅ Готово, {user_name}! Хотелка: {name} — {price:,.0f}₽",
        reply_markup=await get_main_menu_keyboard(message.from_user.id),
    )
    await state.clear()


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
    current_state = await state.get_state()
    await state.clear()

    if current_state and (
        current_state.startswith("CriticalReset.") or current_state.startswith("FreshStart.")
    ):
        cancel_text = (
            phrases.CANCEL_CRITICAL_RESET
            if current_state.startswith("CriticalReset.")
            else phrases.CANCEL_FRESH_START
        )
        await callback.message.edit_text(text=cancel_text)
        if settings.EXPENSE_SIMPLE_CHECK:
            await callback.message.answer(
                text="\u200b",
                reply_markup=get_main_reply_keyboard(),
            )
        return

    user_name = callback.from_user.first_name or phrases.FALLBACK_NAME
    await callback.message.edit_text(
        text=phrases.BACK_NAV.format(name=user_name),
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
    balance = "неизвестно"
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
        user_id, 0, pending["amount"], pending["description"], expense.id,
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
        user_name = message.from_user.first_name or phrases.FALLBACK_NAME
        await state.set_state(AddExpense.waiting_for_amount)
        await message.answer(
            text=phrases.ADD_EXPENSE_PROMPT.format(name=user_name),
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
        budget = await get_budget_or_none(message.from_user.id)
        if not budget:
            user_name = message.from_user.first_name or phrases.FALLBACK_NAME
            await message.answer(
                text=phrases.NO_BUDGET_SETTINGS.format(name=user_name),
                reply_markup=await get_main_menu_keyboard(message.from_user.id),
            )
            return
        await message.answer(
            text=phrases.BTN_SETTINGS,
            reply_markup=get_settings_keyboard(),
        )
        return

    if btn_text == phrases.BTN_HELP:
        user_name = message.from_user.first_name or phrases.FALLBACK_NAME
        await message.answer(
            text=phrases.HELP_TEXT.format(name=user_name),
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
        user_name = message.from_user.first_name or phrases.FALLBACK_NAME
        await message.answer(
            text=phrases.UNRECOGNIZED.format(name=user_name),
            reply_markup=await get_main_menu_keyboard(message.from_user.id),
        )
        return

    parsed_list = parse_multi_expense_text(text)
    if not parsed_list:
        return

    await get_or_create_user(
        telegram_id=message.from_user.id,
        first_name=message.from_user.first_name,
        username=message.from_user.username,
    )

    user_id = message.from_user.id
    sent_dup, all_silent, lines, total_spare, first_id = await _save_expenses_from_parsed_list(
        user_id, parsed_list, message
    )
    if sent_dup:
        return

    if all_silent:
        return

    if not lines:
        await message.answer(phrases.ERR_EXPENSE_SAVE)
        return

    user_name = safe(message.from_user.first_name or phrases.FALLBACK_NAME)

    total_round_up = ""
    if total_spare > 0:
        new_total, goal_name = await add_spare_change_to_goal(user_id, total_spare)
        total_round_up = phrases.ROUND_UP.format(
            amount=int(total_spare), goal=goal_name, total=int(new_total)
        )

    kb = _build_expense_check_kb(first_id, len(lines))

    response_text = phrases.EXPENSE_SAVED_ALL.format(
        name=user_name, lines="\n".join(lines), round_up=total_round_up
    )
    await message.answer(text=response_text, reply_markup=kb)
