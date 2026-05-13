from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime
import re

from ...db.database import async_session_maker
from ...db.models.models import User, Budget

router = Router()


class EditBudget(StatesGroup):
    choosing_field = State()
    waiting_for_income = State()
    waiting_for_mandatory = State()
    waiting_for_black_day = State()
    waiting_for_wishlist = State()


@router.message(Command("settings"))
async def cmd_settings(message: Message, state: FSMContext):
    user_name = message.from_user.first_name or "друг"
    
    async with async_session_maker() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await message.answer(f"Привет, {user_name}! Ты ещё не настраивал(а) бюджет. Напиши /start")
            return
        
        result = await session.execute(
            select(Budget).where(
                Budget.user_id == user.telegram_id,
                Budget.month == datetime.now().strftime("%Y-%m")
            )
        )
        budget = result.scalar_one_or_none()
        
        if not budget:
            await message.answer(f"Привет, {user_name}! У тебя нет бюджета на этот месяц. Напиши /start")
            return
        
        greeting = f"Привет, {user_name}! Что хочешь изменить?"
        
        await message.answer(
            text=f"{greeting}\n\n"
                 f"📊 <b>Твой текущий бюджет:</b>\n\n"
                 f"• Общий доход: {budget.total_income:,.0f}₽\n"
                 f"• Обязательные: {budget.mandatory_payments:,.0f}₽\n"
                 f"• Чёрный день: {budget.black_day_fund:,.0f}₽\n"
                 f"• {budget.wishlist_name}: {budget.wishlist_target:,.0f}₽\n"
                 f"• Дневной лимит: {budget.daily_limit:,.0f}₽\n\n"
                 f"Что меняем?\n\n"
                 "1️⃣ — Доход\n"
                 "2️⃣ — Обязательные\n"
                 "3️⃣ — Чёрный день\n"
                 "4️⃣ — Хотелку"
        )
        await state.set_state(EditBudget.choosing_field)


@router.message(EditBudget.choosing_field)
async def process_field_choice(message: Message, state: FSMContext):
    choice = message.text.strip()
    
    field_map = {
        "1": ("доход", EditBudget.waiting_for_income),
        "2": ("обязательные платежи", EditBudget.waiting_for_mandatory),
        "3": ("чёрный день", EditBudget.waiting_for_black_day),
        "4": ("хотелку", EditBudget.waiting_for_wishlist),
    }
    
    if choice in field_map:
        field_name, next_state = field_map[choice]
        await message.answer(f"Введи новую сумму на {field_name}:")
        await state.set_state(next_state)
    else:
        await message.answer("Выбери число 1-4")


@router.message(EditBudget.waiting_for_income)
async def edit_income(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
        await update_budget_field(message.from_user.id, "total_income", amount)
        
        user_name = message.from_user.first_name or "друг"
        await message.answer(f"✅ Готово, {user_name}! Доход обновлён: {amount:,.0f}₽")
        await state.clear()
    except ValueError:
        await message.answer("❌ Введи число. Например: 50000")


@router.message(EditBudget.waiting_for_mandatory)
async def edit_mandatory(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
        await update_budget_field(message.from_user.id, "mandatory_payments", amount)
        
        user_name = message.from_user.first_name or "друг"
        await message.answer(f"✅ Готово, {user_name}! Обязательные платежи: {amount:,.0f}₽")
        await state.clear()
    except ValueError:
        await message.answer("❌ Введи число. Например: 15000")


@router.message(EditBudget.waiting_for_black_day)
async def edit_black_day(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
        await update_budget_field(message.from_user.id, "black_day_fund", amount)
        
        user_name = message.from_user.first_name or "друг"
        await message.answer(f"✅ Готово, {user_name}! Чёрный день: {amount:,.0f}₽")
        await state.clear()
    except ValueError:
        await message.answer("❌ Введи число. Например: 5000")


@router.message(EditBudget.waiting_for_wishlist)
async def edit_wishlist(message: Message, state: FSMContext):
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
    await message.answer(f"✅ Готово, {user_name}! Хотелка: {name} — {price:,.0f}₽")
    await state.clear()


async def update_budget_field(user_id: int, field: str, value):
    async with async_session_maker() as session:
        from sqlalchemy import select, update
        month = datetime.now().strftime("%Y-%m")
        
        result = await session.execute(
            select(Budget).where(
                Budget.user_id == user_id,
                Budget.month == month
            )
        )
        budget = result.scalar_one_or_none()
        
        if budget:
            setattr(budget, field, value)
            await session.commit()