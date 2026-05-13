from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime

from ...db.database import async_session_maker
from ...db.models.models import User, Budget, Expense

router = Router()


def get_main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Бюджет", callback_data="menu_budget")],
        [InlineKeyboardButton(text="💸 Добавить трату", callback_data="menu_add")],
        [InlineKeyboardButton(text="📈 Статус", callback_data="menu_status")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu_settings")],
        [InlineKeyboardButton(text="📋 Помощь", callback_data="menu_help")],
    ])


@router.message(Command("start"))
async def cmd_start(message: Message):
    user_name = message.from_user.first_name or "друг"
    await message.answer(
        text=f"👋 Привет, {user_name}!\n\n"
             "Я — твой финансовый помощник. Давай не дадим деньгам утекать!\n\n"
             "Выбери действие:",
        reply_markup=get_main_menu_keyboard()
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    user_name = message.from_user.first_name or "друг"
    await message.answer(
        text=f"👋 {user_name}, выбери действие:",
        reply_markup=get_main_menu_keyboard()
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    user_name = message.from_user.first_name or "друг"
    await message.answer(
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


@router.message(Command("status"))
async def cmd_status(message: Message):
    user_name = message.from_user.first_name or "друг"
    
    async with async_session_maker() as session:
        from sqlalchemy import select, func
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await message.answer(
                text=f"👋 Привет, {user_name}!\n\n"
                     "У тебя пока нет бюджета. Нажми /start!",
                reply_markup=get_main_menu_keyboard()
            )
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
            await message.answer(
                text=f"👋 Привет, {user_name}!\n\n"
                     "У тебя нет бюджета на этот месяц. Нажми /start!",
                reply_markup=get_main_menu_keyboard()
            )
            return
        
        result = await session.execute(
            select(func.sum(Expense.amount)).where(
                Expense.user_id == user.telegram_id,
                Expense.date >= datetime.now().replace(day=1, hour=0, minute=0, second=0)
            )
        )
        spent = result.scalar() or 0
        
        remaining = budget.total_income - budget.mandatory_payments - budget.black_day_fund - budget.wishlist_target - spent
        daily = budget.daily_limit
        
        await message.answer(
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