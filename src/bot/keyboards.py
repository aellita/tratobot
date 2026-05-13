from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Бюджет", callback_data="menu_budget")],
        [InlineKeyboardButton(text="💸 Добавить трату", callback_data="menu_add")],
        [InlineKeyboardButton(text="📈 Статус", callback_data="menu_status")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu_settings")],
        [InlineKeyboardButton(text="📋 Помощь", callback_data="menu_help")],
    ])


def get_budget_setup_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="budget_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="budget_cancel")],
    ])


def get_settings_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Изменить доход", callback_data="edit_income")],
        [InlineKeyboardButton(text="📌 Изменить обязательные", callback_data="edit_mandatory")],
        [InlineKeyboardButton(text="🆘 Изменить чёрный день", callback_data="edit_black_day")],
        [InlineKeyboardButton(text="🎯 Изменить хотелку", callback_data="edit_wishlist")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_back")],
    ])


def get_cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
    ])