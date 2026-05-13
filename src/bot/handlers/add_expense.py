from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime
import re

from ...db.database import async_session_maker
from ...db.models.models import User, Budget, Expense

router = Router()


class AddExpense(StatesGroup):
    waiting_for_amount = State()


CATEGORIES = {
    "еда": "🍔 Еда",
    "транспорт": "🚌 Транспорт",
    "развлечения": "🎮 Развлечения",
    "покупки": "🛒 Покупки",
    "подписки": "📱 Подписки",
    "другое": "📦 Другое",
}

DEFAULT_KEYWORDS = {
    "еда": ["еда", "продукты", "обед", "ужин", "завтрак", "кофе", "чай", "пицца", "суши"],
    "транспорт": ["такси", "автобус", "метро", "бензин", "парковка"],
    "развлечения": ["кино", "концерт", "игра", "steam", "netflix"],
    "покупки": ["одежда", "обувь", "косметика"],
    "подписки": ["подписка", "netflix", "spotify", "youtube"],
}


def detect_category(text: str) -> str:
    text_lower = text.lower()
    for category, keywords in DEFAULT_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text_lower:
                return category
    return "другое"


@router.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext):
    user_name = message.from_user.first_name or "друг"
    
    async with async_session_maker() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await message.answer(f"Привет, {user_name}! Сначала напиши /start")
            return
        
        month = datetime.now().strftime("%Y-%m")
        result = await session.execute(
            select(Budget).where(
                Budget.user_id == user.telegram_id,
                Budget.month == month
            )
        )
        budget = result.scalar_one_or_none()
        
        if not budget:
            await message.answer(f"Привет, {user_name}! Напиши /start чтобы настроить бюджет")
            return
    
    await state.set_state(AddExpense.waiting_for_amount)
    await message.answer(
        text=f"💸 Добавить трату, {user_name}!\n\n"
             "Введи сумму и описание:\n"
             "Например: 500 кофе"
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
    
    user_id = message.from_user.id
    
    async with async_session_maker() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await state.clear()
            return
        
        expense = Expense(
            user_id=user.telegram_id,
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
             f"📝 Описание: {description or '—'}\n\n"
             f"Пиши /add чтобы добавить ещё\n"
             f"Или /status чтобы посмотреть баланс"
    )
    
    await state.clear()


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    user_name = message.from_user.first_name or "друг"
    await message.answer(f"❌ Отменено, {user_name}")