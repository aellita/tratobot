import random
import re
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select, func

from ...db.database import async_session_maker
from ...db.models.models import User, Budget, Expense
from ...services.budget_service import save_budget, update_budget_field
from ...services.categorization import CATEGORIES, GREETINGS, detect_category
from ...services.expense_service import create_expense
from ...services.user_service import get_or_create_user
from ..keyboards import get_cancel_keyboard, get_main_menu_keyboard, get_settings_keyboard

router = Router()


class BudgetSetup(StatesGroup):
    waiting_for_income = State()
    waiting_for_mandatory = State()
    waiting_for_black_day = State()
    waiting_for_wishlist_name = State()


class EditBudget(StatesGroup):
    choosing_field = State()
    waiting_for_income = State()
    waiting_for_mandatory = State()
    waiting_for_black_day = State()
    waiting_for_wishlist = State()


class AddExpense(StatesGroup):
    waiting_for_amount = State()


async def get_user_or_none(telegram_id: int) -> User | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()


async def get_budget_or_none(telegram_id: int) -> Budget | None:
    month = datetime.now().strftime("%Y-%m")
    async with async_session_maker() as session:
        user = await get_user_or_none(telegram_id)
        if not user:
            return None
        result = await session.execute(
            select(Budget).where(
                Budget.user_id == user.id,
                Budget.month == month
            )
        )
        return result.scalar_one_or_none()


# ============ MENU HANDLERS ============

@router.callback_query(F.data == "menu_back")
async def menu_back(callback: CallbackQuery):
    user_name = callback.from_user.first_name or "друг"
    await callback.message.edit_text(
        text=f"👋 {user_name}, выбери действие:",
        reply_markup=get_main_menu_keyboard()
    )


@router.callback_query(F.data == "menu_help")
async def menu_help(callback: CallbackQuery):
    user_name = callback.from_user.first_name or "друг"
    await callback.message.edit_text(
        text=f"👋 Привет, {user_name}!\n\n"
             "📋 <b>Что я умею:</b>\n\n"
             "📊 <b>Бюджет</b> — настроить и посмотреть\n"
             "💸 <b>Добавить трату</b> — записать расход\n"
             "📈 <b>Статус</b> — сколько осталось\n"
             "⚙️ <b>Настройки</b> — изменить бюджет\n\n"
             "Или просто напиши сумму и описание:\n"
             "\"500 кофе\", \"200 такси\" — я сама разберусь! 😊",
        reply_markup=get_main_menu_keyboard()
    )


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user_name = message.from_user.first_name or "друг"
    greeting = random.choice(GREETINGS)
    await message.answer(text=greeting)
    await message.answer(
        text="📊 Давай настроим бюджет!\n\n"
             "Начнём с фундамента: сколько ресурсов у нас в распоряжении на этот месяц?\n"
             "Чистая математика, никакого осуждения.\n\n"
             "Введи общую сумму (например: 50000)",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(BudgetSetup.waiting_for_income)


@router.callback_query(F.data == "menu_status")
async def menu_status(callback: CallbackQuery):
    user_name = callback.from_user.first_name or "друг"

    user = await get_user_or_none(callback.from_user.id)
    if not user:
        await callback.message.edit_text(
            text=f"👋 Привет, {user_name}!\n\n"
                 "У тебя пока нет бюджета. Нажми /start!",
            reply_markup=get_main_menu_keyboard()
        )
        return

    month = datetime.now().strftime("%Y-%m")
    async with async_session_maker() as session:
        result = await session.execute(
            select(Budget).where(
                Budget.user_id == user.id,
                Budget.month == month
            )
        )
        budget = result.scalar_one_or_none()

        if not budget:
            await callback.message.edit_text(
                text=f"👋 Привет, {user_name}!\n\n"
                     "У тебя нет бюджета на этот месяц. Нажми /start!",
                reply_markup=get_main_menu_keyboard()
            )
            return

        result = await session.execute(
            select(func.sum(Expense.amount)).where(
                Expense.user_id == user.id,
                Expense.date >= datetime.now().replace(day=1, hour=0, minute=0, second=0)
            )
        )
        spent = result.scalar() or 0

    remaining = budget.total_income - budget.mandatory_payments - budget.black_day_fund - budget.wishlist_target - spent
    daily = budget.daily_limit

    await callback.message.edit_text(
        text=f"📊 <b>Статус на {datetime.now().strftime('%d %B')}:</b>\n\n"
             f"💰 <b>Дневной лимит:</b> {daily:,.0f}₽\n"
             f"📈 <b>Общий:</b> {budget.total_income:,.0f}₽\n"
             f"📉 <b>Потрачено:</b> {spent:,.0f}₽\n"
             f"📌 <b>Обязательные:</b> {budget.mandatory_payments:,.0f}₽\n"
             f"🆘 <b>Чёрный день:</b> {budget.black_day_fund:,.0f}₽\n"
             f"🎯 <b>{budget.wishlist_name}:</b> {budget.wishlist_target:,.0f}₽\n\n"
             f"💵 <b>Осталось:</b> {remaining:,.0f}₽",
        reply_markup=get_main_menu_keyboard()
    )


# ============ BUDGET SETUP ============

@router.callback_query(F.data == "menu_budget")
async def menu_budget(callback: CallbackQuery, state: FSMContext):
    greeting = random.choice(GREETINGS)

    await callback.message.edit_text(text=greeting)
    await callback.message.answer(
        text="📊 Давай настроим бюджет!\n\n"
             "Начнём с фундамента: сколько ресурсов у нас в распоряжении на этот месяц?\n"
             "Чистая математика, никакого осуждения.\n\n"
             "Введи общую сумму (например: 50000)"
    )
    await state.set_state(BudgetSetup.waiting_for_income)


@router.message(BudgetSetup.waiting_for_income)
async def process_income(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
        await state.update_data(income=amount)

        await message.answer(
            text="✅ Запомнил!\n\n"
                 "Теперь отсечем всё лишнее: аренду, счета и прочую бытовую рутину.\n"
                 "Сколько у нас уходит на обязательные платежи?"
        )
        await state.set_state(BudgetSetup.waiting_for_mandatory)
    except ValueError:
        await message.answer("❌ Введи число. Например: 50000")


@router.message(BudgetSetup.waiting_for_mandatory)
async def process_mandatory(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
        await state.update_data(mandatory=amount)

        await message.answer(
            text="✅ Хорошо.\n\n"
                 "Ок. А теперь давай создадим твою подушку безопасности на случай внезапных приключений.\n"
                 "Сколько будем откладывать в месяц в \"Чёрный день\", чтобы ты спал(а) спокойно?"
        )
        await state.set_state(BudgetSetup.waiting_for_black_day)
    except ValueError:
        await message.answer("❌ Введи число. Например: 15000")


@router.message(BudgetSetup.waiting_for_black_day)
async def process_black_day(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
        await state.update_data(black_day=amount)

        await message.answer(
            text="✅ Отлично!\n\n"
                 "А теперь о приятном: ради какой большой цели мы всё это затеяли?\n\n"
                 "Напиши название и сумму одним сообщением:\n"
                 "Например: Ноутбук 50000"
        )
        await state.set_state(BudgetSetup.waiting_for_wishlist_name)
    except ValueError:
        await message.answer("❌ Введи число. Например: 5000")


@router.message(BudgetSetup.waiting_for_wishlist_name)
async def process_wishlist_name(message: Message, state: FSMContext):
    text = message.text.strip()

    numbers = re.findall(r'[\d ]+', text.replace(',', '.'))

    name = text
    price = 0
    for num_str in numbers:
        try:
            price = float(num_str.replace(" ", ""))
            if price > 0:
                name = text.replace(num_str, "").strip()
                if not name:
                    name = "Мечта"
                break
        except:
            continue

    await state.update_data(wishlist_name=name, wishlist_price=price)

    data = await state.get_data()
    user = await get_or_create_user(
        telegram_id=message.from_user.id,
        first_name=message.from_user.first_name,
        username=message.from_user.username
    )

    month = datetime.now().strftime("%Y-%m")

    wishlist_name = data.get("wishlist_name", "Мечта")
    wishlist_price = data.get("wishlist_price", price)

    await save_budget(
        user_id=user.id,
        month=month,
        income=data["income"],
        mandatory=data["mandatory"],
        black_day=data["black_day"],
        wishlist_name=wishlist_name,
        wishlist_price=wishlist_price
    )

    daily_limit = (data["income"] - data["mandatory"] - data["black_day"] - wishlist_price) / 30
    daily_limit = max(daily_limit, 0)

    user_name = message.from_user.first_name or "друг"

    await message.answer(
        text=f"🎉 <b>Готово!</b> {user_name}!\n\n"
             f"📊 Бюджет на {month}:\n"
             f"• Общий доход: {data['income']:,.0f}₽\n"
             f"• Обязательные: {data['mandatory']:,.0f}₽\n"
             f"• Чёрный день: {data['black_day']:,.0f}₽\n"
             f"• {wishlist_name}: {wishlist_price:,.0f}₽\n\n"
             f"💰 <b>Дневной лимит: {daily_limit:,.0f}₽</b>",
        reply_markup=get_main_menu_keyboard()
    )

    await state.clear()


# ============ ADD EXPENSE ============

@router.callback_query(F.data == "menu_add")
async def menu_add(callback: CallbackQuery, state: FSMContext):
    user_name = callback.from_user.first_name or "друг"
    await state.set_state(AddExpense.waiting_for_amount)
    await callback.message.edit_text(
        text=f"💸 Добавить трату, {user_name}!\n\n"
             "Введи сумму и описание:\n"
             "Например: 500 кофе",
        reply_markup=get_cancel_keyboard()
    )


@router.message(AddExpense.waiting_for_amount)
async def process_expense(message: Message, state: FSMContext):
    text = message.text.strip()

    amount = 0
    description = text

    numbers = re.findall(r'\d+(?:[,\.]\d+)?', text)
    for num_str in numbers:
        try:
            amount = float(num_str.replace(",", "."))
            if amount > 0:
                description = text.replace(num_str, "").strip()
                break
        except:
            continue

    if amount <= 0:
        await message.answer("❌ Введи сумму. Например: 500 кофе")
        return

    category = detect_category(description)
    category_emoji = CATEGORIES.get(category, "📦")

    user = await get_or_create_user(
        telegram_id=message.from_user.id,
        first_name=message.from_user.first_name,
        username=message.from_user.username
    )

    async with async_session_maker() as session:
        expense = Expense(
            user_id=user.id,
            amount=amount,
            description=description or category,
            date=datetime.utcnow()
        )
        session.add(expense)
        await session.commit()

    user_name = message.from_user.first_name or "друг"

    await message.answer(
        text=f"✅ Записано, {user_name}!\n\n"
             f"💰 Сумма: {amount:,.0f}₽\n"
             f"{category_emoji} Категория: {category.capitalize()}\n"
             f"📝 Описание: {description or '—'}",
        reply_markup=get_main_menu_keyboard()
    )

    await state.clear()


# ============ SETTINGS ============

@router.callback_query(F.data == "menu_settings")
async def menu_settings(callback: CallbackQuery, state: FSMContext):
    user_name = callback.from_user.first_name or "друг"

    budget = await get_budget_or_none(callback.from_user.id)
    if not budget:
        await callback.message.edit_text(
            text=f"👋 Привет, {user_name}!\nТы ещё не настраивал бюджет. Нажми /start!",
            reply_markup=get_main_menu_keyboard()
        )
        return

    await callback.message.edit_text(
        text=f"⚙️ {user_name}, что меняем?\n\n"
             f"📊 Текущий бюджет:\n"
             f"• Доход: {budget.total_income:,.0f}₽\n"
             f"• Обязательные: {budget.mandatory_payments:,.0f}₽\n"
             f"• Чёрный день: {budget.black_day_fund:,.0f}₽\n"
             f"• {budget.wishlist_name}: {budget.wishlist_target:,.0f}₽",
        reply_markup=get_settings_keyboard()
    )


@router.callback_query(F.data == "edit_income")
async def edit_income(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditBudget.waiting_for_income)
    await callback.message.edit_text(
        text="💰 Введи новый доход:",
        reply_markup=get_cancel_keyboard()
    )


@router.callback_query(F.data == "edit_mandatory")
async def edit_mandatory(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditBudget.waiting_for_mandatory)
    await callback.message.edit_text(
        text="📌 Введи новую сумму обязательных:",
        reply_markup=get_cancel_keyboard()
    )


@router.callback_query(F.data == "edit_black_day")
async def edit_black_day(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditBudget.waiting_for_black_day)
    await callback.message.edit_text(
        text="🆘 Введи новую сумму чёрного дня:",
        reply_markup=get_cancel_keyboard()
    )


@router.callback_query(F.data == "edit_wishlist")
async def edit_wishlist(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditBudget.waiting_for_wishlist)
    await callback.message.edit_text(
        text="🎯 Введи название и сумму хотелки:\n"
             "Например: Ноутбук 50000",
        reply_markup=get_cancel_keyboard()
    )


@router.message(EditBudget.waiting_for_income)
async def save_income(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
        await update_budget_field(message.from_user.id, "total_income", amount)
        user_name = message.from_user.first_name or "друг"
        await message.answer(
            text=f"✅ Готово, {user_name}! Доход: {amount:,.0f}₽",
            reply_markup=get_main_menu_keyboard()
        )
        await state.clear()
    except ValueError:
        await message.answer("❌ Введи число. Например: 50000")


@router.message(EditBudget.waiting_for_mandatory)
async def save_mandatory(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
        await update_budget_field(message.from_user.id, "mandatory_payments", amount)
        user_name = message.from_user.first_name or "друг"
        await message.answer(
            text=f"✅ Готово, {user_name}! Обязательные: {amount:,.0f}₽",
            reply_markup=get_main_menu_keyboard()
        )
        await state.clear()
    except ValueError:
        await message.answer("❌ Введи число. Например: 15000")


@router.message(EditBudget.waiting_for_black_day)
async def save_black_day(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
        await update_budget_field(message.from_user.id, "black_day_fund", amount)
        user_name = message.from_user.first_name or "друг"
        await message.answer(
            text=f"✅ Готово, {user_name}! Чёрный день: {amount:,.0f}₽",
            reply_markup=get_main_menu_keyboard()
        )
        await state.clear()
    except ValueError:
        await message.answer("❌ Введи число. Например: 5000")


@router.message(EditBudget.waiting_for_wishlist)
async def save_wishlist(message: Message, state: FSMContext):
    text = message.text.strip()

    numbers = re.findall(r'[\d ]+', text.replace(',', '.'))

    name = text
    price = 0
    for num_str in numbers:
        try:
            price = float(num_str.replace(" ", ""))
            if price > 0:
                name = text.replace(num_str, "").strip()
                if not name:
                    name = "Мечта"
                break
        except:
            continue

    await update_budget_field(message.from_user.id, "wishlist_name", name)
    await update_budget_field(message.from_user.id, "wishlist_target", price)

    user_name = message.from_user.first_name or "друг"
    await message.answer(
        text=f"✅ Готово, {user_name}! Хотелка: {name} — {price:,.0f}₽",
        reply_markup=get_main_menu_keyboard()
    )
    await state.clear()


# ============ CANCEL ============

@router.callback_query(F.data == "cancel")
async def cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_name = callback.from_user.first_name or "друг"
    await callback.message.edit_text(
        text=f"❌ Отменено, {user_name}!",
        reply_markup=get_main_menu_keyboard()
    )


# ============ TEXT INPUT (free form) ============

@router.message()
async def handle_text(message: Message, state: FSMContext):
    text = message.text.strip()

    if text.startswith('/'):
        return

    numbers = re.findall(r'\d+(?:[,\.]\d+)?', text)
    for num_str in numbers:
        try:
            amount = float(num_str.replace(",", "."))
            if amount > 0:
                description = text.replace(num_str, "").strip()

                category = detect_category(description)
                category_emoji = CATEGORIES.get(category, "📦")

                user = await get_or_create_user(
                    telegram_id=message.from_user.id,
                    first_name=message.from_user.first_name,
                    username=message.from_user.username
                )

                async with async_session_maker() as session:
                    expense = Expense(
                        user_id=user.id,
                        amount=amount,
                        description=description or category,
                        date=datetime.utcnow()
                    )
                    session.add(expense)
                    await session.commit()

                user_name = message.from_user.first_name or "друг"

                await message.answer(
                    text=f"✅ Записано, {user_name}!\n\n"
                         f"💰 {amount:,.0f}₽ — {description or category.capitalize()}\n"
                         f"{category_emoji}",
                    reply_markup=get_main_menu_keyboard()
                )
                return
        except:
            continue

    user_name = message.from_user.first_name or "друг"
    await message.answer(
        text=f"👋 {user_name}, не поняла...\n\n"
             "Напиши сумму и описание, например:\n"
             "\"500 кофе\" или нажми кнопку в меню",
        reply_markup=get_main_menu_keyboard()
    )
