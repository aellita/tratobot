from datetime import datetime

from sqlalchemy import select, func
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from ..db.database import async_session_maker
from ..db.models.models import Budget, Expense


async def get_main_menu_keyboard(telegram_id: int = None):
    button_text = "💰 Дневной лимит"
    if telegram_id:
        text = await _get_daily_limit_text(telegram_id)
        if text:
            button_text = text

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Добавить трату", callback_data="menu_add")],
        [InlineKeyboardButton(text=button_text, callback_data="menu_daily")],
        [InlineKeyboardButton(text="📜 История", callback_data="menu_history")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu_settings")],
        [InlineKeyboardButton(text="📋 Помощь", callback_data="menu_help")],
    ])


async def _get_daily_limit_text(telegram_id: int) -> str | None:
    async with async_session_maker() as session:
        month = datetime.now().strftime("%Y-%m")
        result = await session.execute(
            select(Budget).where(
                Budget.telegram_id == telegram_id,
                Budget.month == month
            )
        )
        budget = result.scalar_one_or_none()
        if not budget or budget.daily_limit <= 0:
            return None

        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        result = await session.execute(
            select(func.sum(Expense.amount)).where(
                Expense.telegram_id == telegram_id,
                Expense.is_deleted == False,
                Expense.date >= today_start
            )
        )
        spent_today = result.scalar() or 0

    remaining = max(budget.daily_limit - spent_today, 0)
    text = f"💰 Дневной лимит: {remaining:,.0f}₽"
    if len(text) > 64:
        return None
    return text


def get_settings_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Обновить доход", callback_data="edit_income")],
        [InlineKeyboardButton(text="➕ Добавить доход", callback_data="add_income")],
        [InlineKeyboardButton(text="📌 Обязательные", callback_data="edit_mandatory")],
        [InlineKeyboardButton(text="🆘 Чёрный день", callback_data="edit_black_day")],
        [InlineKeyboardButton(text="🎯 Хотелка", callback_data="edit_wishlist")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_back")],
    ])


def get_cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="cancel")],
    ])


def get_onboarding_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_step")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="cancel")],
    ])


def get_start_choice_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ В главное меню", callback_data="open_menu")],
        [InlineKeyboardButton(text="🔄 Перезапустить бюджет", callback_data="reset_budget")],
    ])
