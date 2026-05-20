from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Добавить трату", callback_data="menu_add")],
        [InlineKeyboardButton(text="💰 Дневной лимит", callback_data="menu_daily")],
        [InlineKeyboardButton(text="📜 История", callback_data="menu_history")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu_settings")],
        [InlineKeyboardButton(text="📋 Помощь", callback_data="menu_help")],
    ])


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
