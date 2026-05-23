import logging
import random
import re
from datetime import datetime

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, func

from ...db.database import async_session_maker
from ...db.models.models import User, Budget, Expense, Category
from ...services.budget_service import save_budget, update_budget_field, reconcile_budget_with_reality
from ...services.categorization import GREETINGS, detect_category_db, get_category_display, add_keyword_to_category, get_user_categories, seed_user_categories, clean_and_normalize, _dump_keywords
from ...services.expense_service import parse_expense_text
from ...services.user_service import get_or_create_user
from ..keyboards import (
    get_cancel_keyboard,
    get_main_menu_keyboard,
    get_onboarding_keyboard,
    get_period_start_keyboard,
    get_settings_keyboard,
    get_start_choice_keyboard,
)
from ...services.budget_service import delete_current_budget

router = Router()


class BudgetSetup(StatesGroup):
    waiting_for_income = State()
    waiting_for_period_start = State()
    waiting_for_mandatory = State()
    waiting_for_black_day = State()
    waiting_for_wishlist_name = State()


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


async def get_user_or_none(telegram_id: int) -> User | None:
    async with async_session_maker() as session:
        return await session.get(User, telegram_id)


async def get_budget_or_none(telegram_id: int) -> Budget | None:
    month = datetime.now().strftime("%Y-%m")
    async with async_session_maker() as session:
        result = await session.execute(
            select(Budget).where(
                Budget.telegram_id == telegram_id,
                Budget.month == month
            )
        )
        return result.scalar_one_or_none()


_last_keyboard = {}  # chat_id -> message_id


async def _cleanup_keyboard(bot: Bot, chat_id: int):
    msg_id = _last_keyboard.pop(chat_id, None)
    if msg_id:
        try:
            await bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=None
            )
        except Exception:
            pass


def _track_keyboard(chat_id: int, message_id: int):
    _last_keyboard[chat_id] = message_id


async def _cleanup_old_buttons(state: FSMContext, bot: Bot):
    data = await state.get_data()
    msg_id = data.get("_last_msg_id")
    chat_id = data.get("_last_chat_id")
    if msg_id and chat_id:
        try:
            await bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=None
            )
        except Exception:
            pass


async def _save_msg_id(state: FSMContext, msg: Message):
    await state.update_data(_last_msg_id=msg.message_id, _last_chat_id=msg.chat.id)


# ============ MENU HANDLERS ============

@router.callback_query(F.data == "menu_back")
async def menu_back(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    user_name = callback.from_user.first_name or "друг"
    await callback.message.edit_text(
        text=f"👋 {user_name}, выбери действие:",
        reply_markup=await get_main_menu_keyboard(callback.from_user.id)
    )
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


@router.callback_query(F.data == "menu_help")
async def menu_help(callback: CallbackQuery):
    await callback.answer()
    user_name = callback.from_user.first_name or "друг"
    await callback.message.edit_text(
        text=f"👋 Привет, {user_name}!\n\n"
             "📋 <b>Что я умею:</b>\n\n"
             "💸 <b>Добавить трату</b> — записать расход\n"
             "📈 <b>Статус</b> — сколько осталось\n"
             "⚙️ <b>Настройки</b> — изменить бюджет\n\n"
             "Или просто напиши сумму и описание:\n"
             "\"500 кофе\", \"200 такси\" — я сама разберусь! 😊",
        reply_markup=await get_main_menu_keyboard(callback.from_user.id)
    )
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await _cleanup_keyboard(message.bot, message.chat.id)
    telegram_id = message.from_user.id
    user_name = message.from_user.first_name or "друг"

    user = await get_user_or_none(telegram_id)

    if not user:
        await get_or_create_user(
            telegram_id=telegram_id,
            first_name=message.from_user.first_name,
            username=message.from_user.username
        )
        greeting = random.choice(GREETINGS)
        await message.answer(text=greeting)

        sent = await message.answer(
            text="📊 Давай настроим бюджет!\n\n"
                 "Начнём с фундамента: сколько ресурсов у нас в распоряжении на этот месяц?\n"
                 "Чистая математика, никакого осуждения.\n\n"
                 "Введи общую сумму (например: 50000)",
            reply_markup=get_onboarding_keyboard()
        )
        await _save_msg_id(state, sent)
        await state.set_state(BudgetSetup.waiting_for_income)
    else:
        await message.answer(
            text=f"👋 Рад видеть тебя снова, {user_name}!\n\n"
                 "Ты уже настроил свой бюджет. Кубышка и Мечта в безопасности.\n"
                 "Что хочешь сделать?",
            reply_markup=get_start_choice_keyboard()
        )


@router.callback_query(F.data == "open_menu")
async def open_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    user_name = callback.from_user.first_name or "друг"
    await callback.message.edit_text(
        text=f"👋 {user_name}, выбери действие:",
        reply_markup=await get_main_menu_keyboard(callback.from_user.id)
    )
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


@router.callback_query(F.data == "reset_budget")
async def reset_budget(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()

    await get_or_create_user(
        telegram_id=callback.from_user.id,
        first_name=callback.from_user.first_name,
        username=callback.from_user.username
    )

    await delete_current_budget(callback.from_user.id)

    greeting = random.choice(GREETINGS)
    await callback.message.edit_text(text=greeting)

    sent = await callback.message.answer(
        text="📊 Давай настроим бюджет заново!\n\n"
             "Начнём с фундамента: сколько ресурсов у нас в распоряжении на этот месяц?\n"
             "Чистая математика, никакого осуждения.\n\n"
             "Введи общую сумму (например: 50000)",
        reply_markup=get_onboarding_keyboard()
    )
    await _save_msg_id(state, sent)
    await state.set_state(BudgetSetup.waiting_for_income)


@router.callback_query(F.data == "menu_status")
async def menu_status(callback: CallbackQuery):
    await callback.answer()
    user_name = callback.from_user.first_name or "друг"

    user = await get_user_or_none(callback.from_user.id)
    if not user:
        await callback.message.edit_text(
            text=f"👋 Привет, {user_name}!\n\n"
                 "У тебя пока нет бюджета. Нажми /start!",
            reply_markup=await get_main_menu_keyboard(callback.from_user.id)
        )
        return

    month = datetime.now().strftime("%Y-%m")
    async with async_session_maker() as session:
        result = await session.execute(
            select(Budget).where(
                Budget.telegram_id == callback.from_user.id,
                Budget.month == month
            )
        )
        budget = result.scalar_one_or_none()

        if not budget:
            await callback.message.edit_text(
                text=f"👋 Привет, {user_name}!\n\n"
                     "У тебя нет бюджета на этот месяц. Нажми /start!",
                reply_markup=await get_main_menu_keyboard(callback.from_user.id)
            )
            return

        result = await session.execute(
            select(func.sum(Expense.amount)).where(
                Expense.telegram_id == callback.from_user.id,
                Expense.is_deleted == False,
                Expense.date >= datetime.now().replace(day=1, hour=0, minute=0, second=0)
            )
        )
        spent = result.scalar() or 0

    remaining = budget.total_income - budget.mandatory_payments - budget.black_day_fund - spent
    daily = budget.daily_limit
    days_left = budget.days_remaining
    period_text = f" (с {budget.period_start_day}-го)" if budget.period_start_day != 1 else ""

    await callback.message.edit_text(
        text=f"📊 <b>Статус на {datetime.now().strftime('%d %B')}:</b>\n\n"
             f"💰 <b>Дневной лимит:</b> {daily:,.0f}₽\n"
             f"📈 <b>Общий:</b> {budget.total_income:,.0f}₽\n"
             f"📉 <b>Потрачено:</b> {spent:,.0f}₽\n"
             f"📌 <b>Обязательные:</b> {budget.mandatory_payments:,.0f}₽\n"
             f"🏦 <b>Кубышка:</b> {budget.black_day_fund:,.0f}₽\n"
             f"🎯 <b>Мечта:</b> {budget.wishlist_target:,.0f}₽\n"
             f"📅 <b>Осталось дней:</b> {days_left}{period_text}\n\n"
             f"💵 <b>Осталось:</b> {remaining:,.0f}₽",
        reply_markup=await get_main_menu_keyboard(callback.from_user.id)
    )
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


@router.callback_query(F.data == "menu_daily")
async def menu_daily(callback: CallbackQuery):
    await callback.answer()
    user_name = callback.from_user.first_name or "друг"

    user = await get_user_or_none(callback.from_user.id)
    if not user:
        await callback.message.edit_text(
            text=f"👋 {user_name}, у тебя пока нет бюджета. Нажми /start!",
            reply_markup=await get_main_menu_keyboard(callback.from_user.id)
        )
        return

    async with async_session_maker() as session:
        month = datetime.now().strftime("%Y-%m")
        result = await session.execute(
            select(Budget).where(
                Budget.telegram_id == callback.from_user.id,
                Budget.month == month
            )
        )
        budget = result.scalar_one_or_none()
        if not budget:
            await callback.message.edit_text(
                text=f"👋 {user_name}, нет бюджета на этот месяц. Нажми /start!",
                reply_markup=await get_main_menu_keyboard(callback.from_user.id)
            )
            return

        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        result = await session.execute(
            select(func.sum(Expense.amount)).where(
                Expense.telegram_id == callback.from_user.id,
                Expense.is_deleted == False,
                Expense.date >= today_start
            )
        )
        spent_today = result.scalar() or 0

    daily = budget.daily_limit
    remaining = max(daily - spent_today, 0)
    days_left = budget.days_remaining

    text = (
        f"💰 <b>Дневной лимит:</b> {daily:,.0f}₽\n"
        f"📉 <b>Потрачено сегодня:</b> {spent_today:,.0f}₽\n"
        f"✅ <b>Осталось на сегодня:</b> {remaining:,.0f}₽\n\n"
        f"📅 <b>Осталось дней:</b> {days_left}\n"
        f"📊 <b>Всего:</b> {budget.total_income:,.0f}₽\n"
        f"📌 <b>Обязательные:</b> {budget.mandatory_payments:,.0f}₽\n"
        f"🏦 <b>Кубышка:</b> {budget.black_day_fund:,.0f}₽\n"
        f"🎯 <b>Мечта:</b> {budget.wishlist_target:,.0f}₽"
    )

    await callback.message.edit_text(text=text, reply_markup=await get_main_menu_keyboard(callback.from_user.id))
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


# ============ ONBOARDING / SKIP ============

@router.callback_query(F.data == "skip_step")
async def skip_step(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    current_state = await state.get_state()

    if current_state == BudgetSetup.waiting_for_income.state:
        await state.update_data(income=0, mandatory=0, black_day=0, wishlist_name="", wishlist_price=0)
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
        await _finish_onboarding(callback, state)
    else:
        await callback.answer()


async def _advance_onboarding(source: CallbackQuery | Message, state: FSMContext):
    current_state = await state.get_state()

    if current_state == BudgetSetup.waiting_for_period_start.state:
        await state.set_state(BudgetSetup.waiting_for_mandatory)
        text = ("✅ Хорошо, период = с 1-го числа.\n\n"
                "Теперь отсечем всё лишнее: аренду, счета и прочую бытовую рутину.\n"
                "Сколько у нас уходит на обязательные платежи?")
        if isinstance(source, CallbackQuery):
            await source.message.edit_text(text=text, reply_markup=get_onboarding_keyboard())
        else:
            await source.answer(text=text, reply_markup=get_onboarding_keyboard())
    elif current_state == BudgetSetup.waiting_for_mandatory.state:
        await state.set_state(BudgetSetup.waiting_for_black_day)
        kw = get_onboarding_keyboard() if isinstance(source, CallbackQuery) else None
        text = "✅ Хорошо.\n\nОк. А теперь давай создадим твою подушку безопасности на случай внезапных приключений.\nСколько будем откладывать в месяц в \"Кубышка\"?"
        if isinstance(source, CallbackQuery):
            await source.message.edit_text(text=text, reply_markup=kw)
        else:
            await source.answer(text=text, reply_markup=get_onboarding_keyboard())
    elif current_state == BudgetSetup.waiting_for_black_day.state:
        await state.set_state(BudgetSetup.waiting_for_wishlist_name)
        text = ("✅ Отлично!\n\n"
                "А теперь о приятном: ради какой большой цели мы всё это затеяли?\n\n"
                "Напиши название и сумму одним сообщением:\n"
                "Например: Ноутбук 50000\n\n"
                "Или нажми «Пропустить»")
        if isinstance(source, CallbackQuery):
            await source.message.edit_text(text=text, reply_markup=get_onboarding_keyboard())
        else:
            await source.answer(text=text, reply_markup=get_onboarding_keyboard())


async def _finish_onboarding(source: CallbackQuery | Message, state: FSMContext):
    data = await state.get_data()
    telegram_id = source.from_user.id if isinstance(source, CallbackQuery) else source.from_user.id

    try:
        await get_or_create_user(
            telegram_id=telegram_id,
            first_name=source.from_user.first_name,
            username=source.from_user.username
        )
    except Exception as e:
        text = "❌ Ошибка базы данных. Попробуй /start ещё раз."
        if isinstance(source, CallbackQuery):
            await source.message.edit_text(text=text)
        else:
            await source.answer(text=text)
        await state.clear()
        return

    month = datetime.now().strftime("%Y-%m")
    wishlist_name = data.get("wishlist_name", "Мечта") or "Мечта"
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
        period_start_day=period_start_day
    )

    import calendar
    today = datetime.now()
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

    user_name = source.from_user.first_name or "друг"

    period_note = f"📅 Период: с {period_start_day}-го числа" if period_start_day != 1 else ""
    text = (f"🎉 <b>Готово!</b> {user_name}!\n\n"
            f"📊 Бюджет на {month}:\n"
            f"• Общий доход: {data.get('income', 0):,.0f}₽\n"
            f"• Обязательные: {data.get('mandatory', 0):,.0f}₽\n"
            f"• Кубышка: {data.get('black_day', 0):,.0f}₽\n"
            f"• Мечта: {wishlist_price:,.0f}₽\n"
            f"{period_note}\n"
            f"💰 <b>Дневной лимит: {daily_limit:,.0f}₽</b>")

    kb = await get_main_menu_keyboard(telegram_id)
    if isinstance(source, CallbackQuery):
        await source.message.edit_text(text=text, reply_markup=kb)
    else:
        await source.answer(text=text, reply_markup=kb)

    await state.clear()


# ============ BUDGET SETUP STEPS ============

@router.message(BudgetSetup.waiting_for_income)
async def process_income(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
    except ValueError:
        await message.answer("❌ Введи число. Например: 50000")
        return

    await _cleanup_old_buttons(state, message.bot)
    await state.update_data(income=amount)
    await state.set_state(BudgetSetup.waiting_for_period_start)
    sent = await message.answer(
        text="✅ Принял!\n\n"
             "📅 А какого числа у тебя обычно начинается финансовый месяц?\n"
             "(Когда приходит основная зарплата)",
        reply_markup=get_period_start_keyboard()
    )
    await _save_msg_id(state, sent)


@router.callback_query(F.data.in_(["period_today", "period_first", "period_other"]))
async def handle_period_start_choice(callback: CallbackQuery, state: FSMContext):
    import calendar
    today = datetime.now()
    current_state = await state.get_state()

    if callback.data == "period_other":
        await callback.message.edit_text(
            text="✏️ Напиши число (1-31):",
            reply_markup=None
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
        await state.set_state(BudgetSetup.waiting_for_mandatory)
        await callback.message.edit_text(
            text="✅ Запомнил!\n\n"
                 "Теперь отсечем всё лишнее: аренду, счета и прочую бытовую рутину.\n"
                 "Сколько у нас уходит на обязательные платежи?",
            reply_markup=get_onboarding_keyboard()
        )
    elif current_state == EditBudget.waiting_for_period_start.state:
        await update_budget_field(callback.from_user.id, "period_start_day", day)
        user_name = callback.from_user.first_name or "друг"
        await callback.message.edit_text(
            text=f"✅ Готово, {user_name}! Период обновлён — с {day}-го числа.",
            reply_markup=await get_main_menu_keyboard(callback.from_user.id)
        )
        await state.clear()

    await callback.answer()


@router.message(BudgetSetup.waiting_for_period_start)
async def process_period_start(message: Message, state: FSMContext):
    import calendar
    today = datetime.now()
    try:
        day = int(message.text.strip())
    except (ValueError, TypeError):
        await message.answer("❌ Введи число. Например: 25")
        return

    if day < 1:
        day = 1
    elif day > 31:
        day = 31

    days_in_month = calendar.monthrange(today.year, today.month)[1]
    if day > days_in_month:
        day = days_in_month

    await _cleanup_old_buttons(state, message.bot)
    await state.update_data(period_start_day=day)
    await state.set_state(BudgetSetup.waiting_for_mandatory)
    sent = await message.answer(
        text="✅ Запомнил!\n\n"
             "Теперь отсечем всё лишнее: аренду, счета и прочую бытовую рутину.\n"
             "Сколько у нас уходит на обязательные платежи?",
        reply_markup=get_onboarding_keyboard()
    )
    await _save_msg_id(state, sent)


@router.message(BudgetSetup.waiting_for_mandatory)
async def process_mandatory(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
    except ValueError:
        await message.answer("❌ Введи число. Например: 15000")
        return

    await _cleanup_old_buttons(state, message.bot)
    await state.update_data(mandatory=amount)
    await state.set_state(BudgetSetup.waiting_for_black_day)
    sent = await message.answer(
        text="✅ Хорошо.\n\n"
             "Ок. А теперь давай создадим твою подушку безопасности на случай внезапных приключений.\n"
             "Сколько будем откладывать в месяц в \"Кубышка\", чтобы ты спал(а) спокойно?",
        reply_markup=get_onboarding_keyboard()
    )
    await _save_msg_id(state, sent)


@router.message(BudgetSetup.waiting_for_black_day)
async def process_black_day(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
    except ValueError:
        await message.answer("❌ Введи число. Например: 5000")
        return

    await _cleanup_old_buttons(state, message.bot)
    await state.update_data(black_day=amount)
    await state.set_state(BudgetSetup.waiting_for_wishlist_name)
    sent = await message.answer(
        text="✅ Отлично!\n\n"
             "А теперь о приятном: ради какой большой цели мы всё это затеяли?\n\n"
             "Напиши название и сумму одним сообщением:\n"
             "Например: Ноутбук 50000\n\n"
             "Или нажми «Пропустить»",
        reply_markup=get_onboarding_keyboard()
    )
    await _save_msg_id(state, sent)


def _parse_wishlist(text: str) -> tuple[str, float]:
    numbers = re.findall(r'[\d ]+', text.replace(',', '.'))
    name = text
    price = 0
    for num_str in numbers:
        try:
            price = float(num_str.replace(" ", ""))
            name = text.replace(num_str, "").strip()
            break
        except:
            continue
    if not name:
        name = "Мечта"
    elif name[0].islower():
        name = name[0].upper() + name[1:]
    return name, price


@router.message(BudgetSetup.waiting_for_wishlist_name)
async def process_wishlist_name(message: Message, state: FSMContext):
    await _cleanup_old_buttons(state, message.bot)
    name, price = _parse_wishlist(message.text.strip())
    await state.update_data(wishlist_name=name, wishlist_price=price)
    await _finish_onboarding(message, state)


# ============ ADD EXPENSE ============

@router.callback_query(F.data == "menu_add")
async def menu_add(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_name = callback.from_user.first_name or "друг"
    await state.set_state(AddExpense.waiting_for_amount)
    await callback.message.edit_text(
        text=f"💸 Добавить трату, {user_name}!\n\n"
             "Введи сумму и описание:\n"
             "Например: 500 кофе",
        reply_markup=get_cancel_keyboard()
    )
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


@router.message(AddExpense.waiting_for_amount)
async def process_expense(message: Message, state: FSMContext):
    parsed = parse_expense_text(message.text.strip())
    if not parsed:
        await message.answer("❌ Введи сумму. Например: 500 кофе")
        return

    amount, description = parsed
    if not description:
        description = "трата"

    user = await get_or_create_user(
        telegram_id=message.from_user.id,
        first_name=message.from_user.first_name,
        username=message.from_user.username
    )

    try:
        cat, matched = await detect_category_db(description, message.from_user.id)
    except Exception as e:
        logging.error("Category detection failed", exc_info=e)
        cat = None
        matched = ""

    cat_id = cat.id if cat else None
    emoji, cat_name = get_category_display(cat.name) if cat else ("📦", "Прочее")

    try:
        async with async_session_maker() as session:
            expense = Expense(
                telegram_id=message.from_user.id,
                amount=amount,
                description=description or cat_name,
                category_id=cat_id,
                date=datetime.utcnow()
            )
            session.add(expense)
            await session.commit()
            expense_id = expense.id
    except Exception as e:
        logging.error("Expense insert failed", exc_info=e)
        cause = getattr(e, "__cause__", None)
        if cause:
            logging.error("Caused by: %s: %s", type(cause).__name__, cause)
        await message.answer("❌ Ошибка при сохранении траты. Попробуй ещё раз.")
        await state.clear()
        return

    await state.clear()
    user_name = message.from_user.first_name or "друг"

    await _cleanup_keyboard(message.bot, message.chat.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Сменить категорию", callback_data=f"change_cat:{expense_id}")],
        [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="menu_back")],
    ])
    msg = await message.answer(
        text=f"✅ Записано, {user_name}!\n\n"
             f"💰 {amount:,.0f}₽ — {description}\n"
             f"{emoji} {cat_name}",
        reply_markup=kb
    )
    _track_keyboard(message.chat.id, msg.message_id)


# ============ CATEGORY CHANGE ============

@router.callback_query(F.data.startswith("change_cat:"))
async def change_category(callback: CallbackQuery):
    await callback.answer()
    expense_id = int(callback.data.split(":")[1])

    categories = await seed_user_categories(callback.from_user.id)

    buttons = []
    row = []
    for i, cat in enumerate(categories):
        emoji, _ = get_category_display(cat.name)
        row.append(InlineKeyboardButton(
            text=f"{emoji} {cat.name}",
            callback_data=f"set_cat:{expense_id}:{cat.id}",
        ))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(
        text="✏️ Новая категория", callback_data=f"new_cat:{expense_id}"
    )])
    buttons.append([InlineKeyboardButton(
        text="⬅️ Назад", callback_data=f"exp_back_cat:{expense_id}"
    )])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(
        text="📂 Выбери категорию:",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("set_cat:"))
async def set_category(callback: CallbackQuery):
    await callback.answer()
    _, expense_id_str, category_id_str = callback.data.split(":")
    expense_id = int(expense_id_str)
    category_id = int(category_id_str)

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
                text="❌ Трата не найдена.",
                reply_markup=await get_main_menu_keyboard(callback.from_user.id),
            )
            return

        result = await session.execute(
            select(Category).where(Category.id == category_id)
        )
        cat = result.scalar_one_or_none()
        if not cat:
            await callback.message.edit_text(
                text="❌ Категория не найдена.",
                reply_markup=await get_main_menu_keyboard(callback.from_user.id),
            )
            return

        expense.category_id = category_id
        await session.commit()

    await add_keyword_to_category(
        callback.from_user.id, category_id, expense.description or "",
    )

    emoji, cat_name = get_category_display(cat.name)
    await callback.message.edit_text(
        text=f"✅ Категория изменена!\n\n"
             f"💰 {expense.amount:,.0f}₽ — {expense.description or cat_name}\n"
             f"{emoji} {cat_name}",
        reply_markup=await get_main_menu_keyboard(callback.from_user.id),
    )


@router.callback_query(F.data.startswith("exp_back_cat:"))
async def back_from_category_change(callback: CallbackQuery):
    await callback.answer()
    user_name = callback.from_user.first_name or "друг"
    await callback.message.edit_text(
        text=f"⬅️ Вернулись, {user_name}!",
        reply_markup=await get_main_menu_keyboard(callback.from_user.id),
    )


@router.callback_query(F.data.startswith("new_cat:"))
async def new_category_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    expense_id = int(callback.data.split(":")[1])
    await state.update_data(new_cat_expense_id=expense_id)
    await state.set_state(CustomCategory.waiting_for_name)
    await callback.message.edit_text(
        text="✏️ Напиши название новой категории:\n\n"
             "Например: Книги, Алкоголь, Животные",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="cancel")],
        ]),
    )


@router.message(CustomCategory.waiting_for_name)
async def save_new_category(message: Message, state: FSMContext):
    name = message.text.strip().capitalize()
    if not name or len(name) > 30:
        await message.answer("❌ Название должно быть от 1 до 30 символов. Попробуй ещё раз:")
        return

    data = await state.get_data()
    expense_id = data.get("new_cat_expense_id")
    if not expense_id:
        await state.clear()
        return

    async with async_session_maker() as session:
        result = await session.execute(
            select(Expense).where(
                Expense.id == expense_id,
                Expense.telegram_id == message.from_user.id,
                Expense.is_deleted == False,
            )
        )
        expense = result.scalar_one_or_none()
        if not expense:
            await message.answer("❌ Трата не найдена.")
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

    user_name = message.from_user.first_name or "друг"
    await state.clear()
    await _cleanup_keyboard(message.bot, message.chat.id)
    msg = await message.answer(
        text=f"✅ Новая категория «{name}» создана, {user_name}!\n"
             f"Я запомнил слово «{expense.description}» для этой категории.",
        reply_markup=await get_main_menu_keyboard(message.from_user.id),
    )
    _track_keyboard(message.chat.id, msg.message_id)


# ============ OVERDRAFT / MORNING HANDLERS ============

@router.callback_query(F.data.startswith("fix_overdraft:"))
async def handle_fix_overdraft(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    action = parts[1]

    if action == "reduce_limit":
        user_name = callback.from_user.first_name or "друг"
        await callback.message.edit_text(
            text=f"✅ Принято, {user_name}! Остаток месяца проживём с урезанным лимитом. "
                 "Я пересчитал бюджет.",
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )
        return

    overdraft = float(parts[2])
    if action == "wishlist":
        budget = await get_budget_or_none(callback.from_user.id)
        if budget and budget.wishlist_target > 0:
            new_target = max(budget.wishlist_target - overdraft, 0)
            await update_budget_field(callback.from_user.id, "wishlist_target", new_target)
            text = f"🎯 Покрыли перерасход из Мечты! Остаток цели: {int(new_target)}₽"
        else:
            text = "❌ Мечта не настроена. Попробуй другой вариант."
        await callback.message.edit_text(text=text, reply_markup=await get_main_menu_keyboard(callback.from_user.id))

    elif action == "cubyshka":
        budget = await get_budget_or_none(callback.from_user.id)
        if budget and budget.black_day_fund > 0:
            new_fund = max(budget.black_day_fund - overdraft, 0)
            await update_budget_field(callback.from_user.id, "black_day_fund", new_fund)
            text = f"🆘 Взяли из Кубышки! Остаток в заначке: {int(new_fund)}₽"
        else:
            text = "❌ Кубышка пуста. Попробуй другой вариант."
        await callback.message.edit_text(text=text, reply_markup=await get_main_menu_keyboard(callback.from_user.id))


@router.callback_query(F.data == "trigger_critical_reset")
async def trigger_critical_reset(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(CriticalReset.waiting_for_real_balance)
    await callback.message.edit_text(
        text="🚀 Давай начнём с чистого листа!\n\n"
             "Сколько у тебя сейчас свободных денег на карте?\n"
             "(Введи сумму, например: 25000)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="cancel")],
        ]),
    )


@router.message(CriticalReset.waiting_for_real_balance)
async def save_real_balance(message: Message, state: FSMContext):
    try:
        real_cash = float(message.text.replace(" ", "").replace(",", "."))
        if real_cash < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи число. Например: 25000")
        return

    new_limit = await reconcile_budget_with_reality(message.from_user.id, real_cash)
    user_name = message.from_user.first_name or "друг"

    await state.clear()
    await _cleanup_keyboard(message.bot, message.chat.id)
    msg = await message.answer(
        text=f"✅ Ревизия завершена, {user_name}!\n\n"
             f"💰 Новый остаток: {int(real_cash)}₽\n"
             f"📅 Осталось дней в периоде\n"
             f"📊 Новый дневной лимит: {int(new_limit)}₽\n\n"
             f"С чистого листа — вперёд! 🚀",
        reply_markup=await get_main_menu_keyboard(message.from_user.id),
    )
    _track_keyboard(message.chat.id, msg.message_id)


# ============ SETTINGS ============

@router.callback_query(F.data == "menu_settings")
async def menu_settings(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_name = callback.from_user.first_name or "друг"

    budget = await get_budget_or_none(callback.from_user.id)
    if not budget:
        await callback.message.edit_text(
            text=f"👋 Привет, {user_name}!\nТы ещё не настраивал бюджет. Нажми /start!",
            reply_markup=await get_main_menu_keyboard(callback.from_user.id)
        )
        return

    period_info = f"📅 Период: с {budget.period_start_day}-го" if budget.period_start_day != 1 else "📅 Период: весь месяц"
    await callback.message.edit_text(
        text=f"⚙️ {user_name}, что меняем?\n\n"
             f"📊 Текущий бюджет:\n"
             f"• Доход: {budget.total_income:,.0f}₽\n"
             f"• Обязательные: {budget.mandatory_payments:,.0f}₽\n"
             f"• Кубышка: {budget.black_day_fund:,.0f}₽\n"
             f"• {budget.wishlist_name}: {budget.wishlist_target:,.0f}₽\n"
             f"{period_info}",
        reply_markup=get_settings_keyboard()
    )
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


@router.callback_query(F.data == "edit_income")
async def edit_income(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(EditBudget.waiting_for_income)
    await callback.message.edit_text(
        text="💰 Введи новую сумму дохода (заменит текущую):",
        reply_markup=get_cancel_keyboard()
    )
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


@router.callback_query(F.data == "add_income")
async def add_income(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(EditBudget.waiting_for_add_income)
    await callback.message.edit_text(
        text="➕ Введи сумму, которую хочешь добавить к текущему доходу:",
        reply_markup=get_cancel_keyboard()
    )
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


@router.callback_query(F.data == "edit_mandatory")
async def edit_mandatory(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(EditBudget.waiting_for_mandatory)
    await callback.message.edit_text(
        text="📌 Введи новую сумму обязательных:",
        reply_markup=get_cancel_keyboard()
    )
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


@router.callback_query(F.data == "edit_black_day")
async def edit_black_day(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(EditBudget.waiting_for_black_day)
    await callback.message.edit_text(
        text="🏦 Введи новую сумму кубышки:",
        reply_markup=get_cancel_keyboard()
    )
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


@router.callback_query(F.data == "edit_wishlist")
async def edit_wishlist(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(EditBudget.waiting_for_wishlist)
    await callback.message.edit_text(
        text="🎯 Введи название и сумму хотелки:\n"
             "Например: Ноутбук 50000",
        reply_markup=get_cancel_keyboard()
    )
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


@router.callback_query(F.data == "edit_period_start")
async def edit_period_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(EditBudget.waiting_for_period_start)
    await callback.message.edit_text(
        text="📅 А какого числа у тебя начинается финансовый месяц?\n"
             "(Когда приходит основная зарплата)",
        reply_markup=get_period_start_keyboard()
    )
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


@router.message(EditBudget.waiting_for_income)
async def save_income(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
        await update_budget_field(message.from_user.id, "total_income", amount)

        await _cleanup_keyboard(message.bot, message.chat.id)
        sent = await message.answer(
            text="✅ Доход обновлён!\n\n"
                 "📅 А какого числа у тебя начинается финансовый месяц?\n"
                 "(Когда приходит основная зарплата)",
            reply_markup=get_period_start_keyboard()
        )
        _track_keyboard(message.chat.id, sent.message_id)
        await state.set_state(EditBudget.waiting_for_period_start)
    except ValueError:
        await message.answer("❌ Введи число. Например: 50000")


@router.message(EditBudget.waiting_for_period_start)
async def save_edit_period_start(message: Message, state: FSMContext):
    import calendar
    today = datetime.now()
    try:
        day = int(message.text.strip())
    except (ValueError, TypeError):
        await message.answer("❌ Введи число. Например: 25")
        return

    if day < 1:
        day = 1
    elif day > 31:
        day = 31

    days_in_month = calendar.monthrange(today.year, today.month)[1]
    if day > days_in_month:
        day = days_in_month

    await update_budget_field(message.from_user.id, "period_start_day", day)
    user_name = message.from_user.first_name or "друг"

    await _cleanup_keyboard(message.bot, message.chat.id)
    msg = await message.answer(
        text=f"✅ Готово, {user_name}! Период обновлён — с {day}-го числа.",
        reply_markup=await get_main_menu_keyboard(message.from_user.id)
    )
    _track_keyboard(message.chat.id, msg.message_id)
    await state.clear()


@router.message(EditBudget.waiting_for_add_income)
async def save_add_income(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
        budget = await get_budget_or_none(message.from_user.id)
        if not budget:
            await message.answer("❌ Сначала настрой бюджет через /start")
            await state.clear()
            return
        new_total = budget.total_income + amount
        await update_budget_field(message.from_user.id, "total_income", new_total)
        user_name = message.from_user.first_name or "друг"

        await _cleanup_keyboard(message.bot, message.chat.id)
        msg = await message.answer(
            text=f"✅ Готово, {user_name}! Доход увеличен на {amount:,.0f}₽\n"
                 f"💰 Текущий доход: {new_total:,.0f}₽",
            reply_markup=await get_main_menu_keyboard(message.from_user.id)
        )
        _track_keyboard(message.chat.id, msg.message_id)
        await state.clear()
    except ValueError:
        await message.answer("❌ Введи число. Например: 10000")


@router.message(EditBudget.waiting_for_mandatory)
async def save_mandatory(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
        await update_budget_field(message.from_user.id, "mandatory_payments", amount)
        user_name = message.from_user.first_name or "друг"

        await _cleanup_keyboard(message.bot, message.chat.id)
        msg = await message.answer(
            text=f"✅ Готово, {user_name}! Обязательные: {amount:,.0f}₽",
            reply_markup=await get_main_menu_keyboard(message.from_user.id)
        )
        _track_keyboard(message.chat.id, msg.message_id)
        await state.clear()
    except ValueError:
        await message.answer("❌ Введи число. Например: 15000")


@router.message(EditBudget.waiting_for_black_day)
async def save_black_day(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
        await update_budget_field(message.from_user.id, "black_day_fund", amount)
        user_name = message.from_user.first_name or "друг"

        await _cleanup_keyboard(message.bot, message.chat.id)
        msg = await message.answer(
            text=f"✅ Готово, {user_name}! Кубышка: {amount:,.0f}₽",
            reply_markup=await get_main_menu_keyboard(message.from_user.id)
        )
        _track_keyboard(message.chat.id, msg.message_id)
        await state.clear()
    except ValueError:
        await message.answer("❌ Введи число. Например: 5000")


@router.message(EditBudget.waiting_for_wishlist)
async def save_wishlist(message: Message, state: FSMContext):
    name, price = _parse_wishlist(message.text.strip())

    await update_budget_field(message.from_user.id, "wishlist_name", name)
    await update_budget_field(message.from_user.id, "wishlist_target", price)

    user_name = message.from_user.first_name or "друг"

    await _cleanup_keyboard(message.bot, message.chat.id)
    msg = await message.answer(
        text=f"✅ Готово, {user_name}! Хотелка: {name} — {price:,.0f}₽",
        reply_markup=await get_main_menu_keyboard(message.from_user.id)
    )
    _track_keyboard(message.chat.id, msg.message_id)
    await state.clear()


# ============ CANCEL / BACK ============

@router.callback_query(F.data == "cancel")
async def cancel(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    user_name = callback.from_user.first_name or "друг"
    await callback.message.edit_text(
        text=f"⬅️ Вернулись, {user_name}!",
        reply_markup=await get_main_menu_keyboard(callback.from_user.id)
    )
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


# ============ UNSUPPORTED CONTENT ============

@router.message(F.voice)
async def handle_voice(message: Message):
    await message.answer(
        "🎤 Я не умею обрабатывать голосовые сообщения.\n"
        "Напиши сумму и описание текстом, например: 500 кофе"
    )


@router.message(F.photo | F.video | F.document | F.sticker | F.animation)
async def handle_media(message: Message):
    await message.answer(
        "📎 Я понимаю только текстовые сообщения.\n"
        "Напиши сумму и описание, например: 500 кофе"
    )


# ============ TEXT INPUT (free form) ============

@router.message()
async def handle_text(message: Message, state: FSMContext):
    text = message.text.strip()

    if text.startswith('/'):
        return

    menu_keywords = {"меню", "помощь", "настройки", "статус", "история", "назад", "отмена"}
    if text.lower() in menu_keywords:
        user_name = message.from_user.first_name or "друг"
        await _cleanup_keyboard(message.bot, message.chat.id)
        msg = await message.answer(
            text=f"👋 {user_name}, воспользуйся кнопками в меню!",
            reply_markup=await get_main_menu_keyboard(message.from_user.id)
        )
        _track_keyboard(message.chat.id, msg.message_id)
        return

    parsed = parse_expense_text(text)
    if parsed:
        amount, description = parsed
        if not description:
            description = "трата"

        await get_or_create_user(
            telegram_id=message.from_user.id,
            first_name=message.from_user.first_name,
            username=message.from_user.username
        )

        try:
            cat, matched = await detect_category_db(description, message.from_user.id)
        except Exception as e:
            logging.error("Category detection failed", exc_info=e)
            cat = None
            matched = ""

        cat_id = cat.id if cat else None
        emoji, cat_name = get_category_display(cat.name) if cat else ("📦", "Прочее")

        try:
            async with async_session_maker() as session:
                expense = Expense(
                    telegram_id=message.from_user.id,
                    amount=amount,
                    description=description or cat_name,
                    category_id=cat_id,
                    date=datetime.utcnow()
                )
                session.add(expense)
                await session.commit()
                expense_id = expense.id
        except Exception as e:
            logging.error("Expense insert failed (free-form)", exc_info=e)
            cause = getattr(e, "__cause__", None)
            if cause:
                logging.error("Caused by: %s: %s", type(cause).__name__, cause)
            await message.answer("❌ Ошибка при сохранении траты. Попробуй ещё раз.")
            return

        user_name = message.from_user.first_name or "друг"

        await _cleanup_keyboard(message.bot, message.chat.id)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Сменить категорию", callback_data=f"change_cat:{expense_id}")],
            [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="menu_back")],
        ])
        msg = await message.answer(
            text=f"✅ Записано, {user_name}!\n\n"
                 f"💰 {amount:,.0f}₽ — {description}\n"
                 f"{emoji} {cat_name}",
            reply_markup=kb
        )
        _track_keyboard(message.chat.id, msg.message_id)
        return

    user_name = message.from_user.first_name or "друг"

    await _cleanup_keyboard(message.bot, message.chat.id)
    msg = await message.answer(
        text=f"👋 {user_name}, не поняла...\n\n"
             "Напиши сумму и описание, например:\n"
             "\"500 кофе\" или нажми кнопку в меню",
        reply_markup=await get_main_menu_keyboard(message.from_user.id)
    )
    _track_keyboard(message.chat.id, msg.message_id)
