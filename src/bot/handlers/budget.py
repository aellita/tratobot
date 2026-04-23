from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime

from ...db.database import async_session_maker
from ...db.models.models import User, Budget


router = Router()


class BudgetSetup(StatesGroup):
    waiting_for_income = State()
    waiting_for_mandatory = State()
    waiting_for_black_day = State()
    waiting_for_wishlist_name = State()
    waiting_for_wishlist_price = State()


class Onboarding(StatesGroup):
    waiting_for_start_confirm = State()


GREETINGS = [
    "Наконец-то ты пришел! Давай сделаем так, чтобы твои деньги перестали испаряться",
    "Наконец-то мы встретились! Я уже подготовил всё для нашего финансового прорыва. Обещаю быть полезным и не слишком занудным",
    "Привет! Я очень ждал твоего появления. Давай наведем порядок в кошельке так, чтобы на всё хватало и еще оставалось",
]


async def get_or_create_user(telegram_id: int, first_name: str = None, username: str = None):
    async with async_session_maker() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                telegram_id=telegram_id,
                first_name=first_name,
                username=username
            )
            session.add(user)
            await session.commit()
        return user


async def save_budget(user_id: int, month: str, income: float, mandatory: float, black_day: float, wishlist_name: str = None, wishlist_price: float = 0):
    async with async_session_maker() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(Budget).where(
                Budget.user_id == user_id,
                Budget.month == month
            )
        )
        budget = result.scalar_one_or_none()
        
        if budget:
            budget.total_income = income
            budget.mandatory_payments = mandatory
            budget.black_day_fund = black_day
            budget.wishlist_target = wishlist_price
        else:
            budget = Budget(
                user_id=user_id,
                month=month,
                total_income=income,
                mandatory_payments=mandatory,
                black_day_fund=black_day,
                wishlist_target=wishlist_price
            )
            session.add(budget)
        
        await session.commit()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    import random
    greeting = random.choice(GREETINGS)
    
    await message.answer(text=greeting)
    await message.answer(
        text="📊 Давай настроим бюджет!\n\n"
             "Начнём с фундамента: сколько ресурсов у нас в распоряжении на этот месяц?\n"
             "Чистая математика, никакого осуждения.\n\n"
             "Введи общую сумму (например: 50000)"
    )
    await state.set_state(BudgetSetup.waiting_for_income)


@router.message(Command("budget"))
async def cmd_budget(message: Message, state: FSMContext):
    await message.answer(
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


import re

@router.message(BudgetSetup.waiting_for_wishlist_name)
async def process_wishlist_name(message: Message, state: FSMContext):
    text = message.text.strip()
    
    # Parse "Название X" or "Название X0" or just "X"
    numbers = re.findall(r'[\d ]+', text.replace(',', '.'))
    
    name = text
    price = 0
    for num_str in numbers:
        try:
            price = float(num_str.replace(" ", ""))
            if price > 0:
                # Extract name = remove this number from text
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
        user_id=user.telegram_id,
        month=month,
        income=data["income"],
        mandatory=data["mandatory"],
        black_day=data["black_day"],
        wishlist_name=wishlist_name,
        wishlist_price=wishlist_price
    )
    
    daily_limit = (data["income"] - data["mandatory"] - data["black_day"] - wishlist_price) / 30
    daily_limit = max(daily_limit, 0)
    
    await message.answer(
        text=f"🎉 <b>Готово!</b>\n\n"
             f"📊 Бюджет на {month}:\n"
             f"• Общий доход: {data['income']:,.0f}₽\n"
             f"• Обязательные: {data['mandatory']:,.0f}₽\n"
             f"• Чёрный день: {data['black_day']:,.0f}₽\n"
             f"• {wishlist_name}: {wishlist_price:,.0f}₽\n\n"
             f"💰 <b>Дневной лимит: {daily_limit:,.0f}₽</b>\n\n"
             f"Теперь пиши /add чтобы добавить трату!"
    )
    
    await state.clear()