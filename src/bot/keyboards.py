from datetime import datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from src.utils import phrases

from ..db.database import async_session_maker
from ..db.models.models import Budget


async def get_main_menu_keyboard(telegram_id: int = None):
    button_text = phrases.BTN_DAILY_LIMIT
    if telegram_id:
        text = await _get_daily_limit_text(telegram_id)
        if text:
            button_text = text

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=phrases.BTN_ADD_EXPENSE, callback_data="menu_add")],
            [InlineKeyboardButton(text=button_text, callback_data="menu_daily")],
            [InlineKeyboardButton(text=phrases.BTN_STATUS, callback_data="menu_status")],
            [InlineKeyboardButton(text=phrases.BTN_HISTORY, callback_data="menu_history")],
            [InlineKeyboardButton(text=phrases.BTN_SETTINGS, callback_data="menu_settings")],
            [InlineKeyboardButton(text=phrases.BTN_HELP, callback_data="menu_help")],
        ]
    )


async def _get_daily_limit_text(telegram_id: int) -> str | None:
    async with async_session_maker() as session:
        month = datetime.now().strftime("%Y-%m")
        result = await session.execute(
            select(Budget).where(Budget.telegram_id == telegram_id, Budget.month == month)
        )
        budget = result.scalar_one_or_none()
        if not budget or budget.daily_limit <= 0:
            return None

    text = f"{phrases.BTN_DAILY_LIMIT}: {budget.daily_limit:,.0f}₽"
    if len(text) > 64:
        return None
    return text


def get_settings_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=phrases.BTN_UPDATE_INCOME, callback_data="edit_income")],
            [InlineKeyboardButton(text=phrases.BTN_ADD_INCOME, callback_data="add_income")],
            [InlineKeyboardButton(text=phrases.BTN_MANDATORY, callback_data="edit_mandatory")],
            [InlineKeyboardButton(text=phrases.BTN_SAVINGS, callback_data="edit_black_day")],
            [InlineKeyboardButton(text=phrases.BTN_WISHLIST, callback_data="edit_wishlist")],
            [
                InlineKeyboardButton(
                    text=phrases.BTN_PERIOD_START, callback_data="edit_period_start"
                )
            ],
            [InlineKeyboardButton(text=phrases.BTN_ROUNDING, callback_data="edit_rounding")],
            [InlineKeyboardButton(text=phrases.BTN_BACK, callback_data="menu_back")],
        ]
    )


def get_period_start_keyboard():
    today = datetime.now()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=phrases.BTN_TODAY.format(day=today.day), callback_data="period_today"
                )
            ],
            [InlineKeyboardButton(text=phrases.BTN_FIRST_DAY, callback_data="period_first")],
            [InlineKeyboardButton(text=phrases.BTN_OTHER_DATE, callback_data="period_other")],
        ]
    )


def get_cancel_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=phrases.BTN_BACK, callback_data="cancel")],
        ]
    )


def get_onboarding_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=phrases.BTN_SKIP, callback_data="skip_step")],
            [InlineKeyboardButton(text=phrases.BTN_BACK, callback_data="cancel")],
        ]
    )


def get_rounding_mode_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=phrases.BTN_ROUNDING_OFF, callback_data="rounding_off")],
            [InlineKeyboardButton(text=phrases.BTN_ROUNDING_10, callback_data="rounding_10")],
            [InlineKeyboardButton(text=phrases.BTN_ROUNDING_100, callback_data="rounding_100")],
            [InlineKeyboardButton(text=phrases.BTN_BACK, callback_data="cancel")],
        ]
    )


def get_start_choice_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=phrases.BTN_TO_MAIN, callback_data="open_menu")],
            [InlineKeyboardButton(text=phrases.BTN_RESTART_BUDGET, callback_data="reset_budget")],
        ]
    )
