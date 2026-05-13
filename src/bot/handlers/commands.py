from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from datetime import datetime

from ...db.database import async_session_maker
from ...db.models.models import User, Budget, Expense

router = Router()


@router.message(Command("help"))
async def cmd_help(message: Message):
    user_name = message.from_user.first_name or "друг"
    await message.answer(
        text=f"👋 Привет, {user_name}!\n\n"
             "📋 <b>Доступные команды:</b>\n\n"
             "/start — Начать или обновить бюджет\n"
             "/budget — Настроить бюджет\n"
             "/settings — Редактировать бюджет\n"
             "/add — Добавить трату\n"
             "/status — Показать статус\n"
             "/help — Помощь"
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
                     "У тебя пока нет бюджета. Напиши /start чтобы настроить!"
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
                     "У тебя нет бюджета на этот месяц. Напиши /start!"
            )
            return
        
        result = await session.execute(
            select(func.sum(Expense.amount)).where(
                Expense.user_id == user.telegram_id,
                func.date(Expense.date) >= datetime.now().replace(day=1)
            )
        )
        spent = result.scalar() or 0
        
        remaining = budget.total_income - budget.mandatory_payments - budget.black_day_fund - budget.wishlist_target - spent
        daily = budget.daily_limit
        
        await message.answer(
            text=f"📊 <b>Статус на {datetime.now().strftime('%d %B')}:</b>\n\n"
                 f"👋 Привет, {user_name}!\n\n"
                 f"💰 <b>Дневной лимит:</b> {daily:,.0f}₽\n"
                 f"📈 <b>Общий доход:</b> {budget.total_income:,.0f}₽\n"
                 f"📉 <b>Потрачено:</b> {spent:,.0f}₽\n"
                 f"📌 <b>Обязательные:</b> {budget.mandatory_payments:,.0f}₽\n"
                 f"🆘 <b>Чёрный день:</b> {budget.black_day_fund:,.0f}₽\n"
                 f"🎯 <b>{budget.wishlist_name}:</b> {budget.wishlist_target:,.0f}₽\n\n"
                 f"💵 <b>Осталось:</b> {remaining:,.0f}₽\n\n"
                 "Используй /add чтобы записать трату\n"
                 "Используй /settings чтобы изменить бюджет"
        )