import logging
import random
import re
from datetime import datetime

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, func

from ...db.database import async_session_maker
from ...db.models.models import User, Budget, Expense, Category, Wishlist, UserSettings
from ...services.budget_service import save_budget, update_budget_field, reconcile_budget_with_reality, apply_reconciliation
from ...services.categorization import GREETINGS, detect_category_db, get_category_display, add_keyword_to_category, get_user_categories, seed_user_categories, clean_and_normalize, _dump_keywords
from ...services.expense_service import parse_expense_text, parse_multi_expense_text, try_apply_round_up
from ...services.user_service import get_or_create_user
from ..keyboards import (
    get_cancel_keyboard,
    get_main_menu_keyboard,
    get_onboarding_keyboard,
    get_period_start_keyboard,
    get_settings_keyboard,
    get_start_choice_keyboard,
    get_rounding_mode_keyboard,
)
from ...services.budget_service import delete_current_budget

router = Router()


class BudgetSetup(StatesGroup):
    waiting_for_income = State()
    waiting_for_period_start = State()
    waiting_for_mandatory = State()
    waiting_for_black_day = State()
    waiting_for_wishlist_name = State()
    waiting_for_rounding_mode = State()


class EditBudget(StatesGroup):
    waiting_for_income = State()
    waiting_for_add_income = State()
    waiting_for_period_start = State()
    waiting_for_mandatory = State()
    waiting_for_black_day = State()
    waiting_for_wishlist = State()


class AddExpense(StatesGroup):
    waiting_for_amount = State()


class CustomCategory(StatesGroup):
    waiting_for_name = State()


class CriticalReset(StatesGroup):
    waiting_for_real_balance = State()


class FreshStart(StatesGroup):
    waiting_for_mandatory = State()
    waiting_for_black_day = State()
    waiting_for_balance = State()


async def get_user_or_none(telegram_id: int) -> User | None:
    async with async_session_maker() as session:
        return await session.get(User, telegram_id)


async def get_budget_or_none(telegram_id: int) -> Budget | None:
    from ...services.budget_service import get_active_budget
    return await get_active_budget(telegram_id)


_last_keyboard = {}  # chat_id -> message_id


async def _cleanup_keyboard(bot: Bot, chat_id: int):
    msg_id = _last_keyboard.pop(chat_id, None)
    if msg_id:
        try:
            await bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=None
            )
        except Exception:
            pass


def _track_keyboard(chat_id: int, message_id: int):
    _last_keyboard[chat_id] = message_id


async def _cleanup_old_buttons(state: FSMContext, bot: Bot):
    data = await state.get_data()
    msg_id = data.get("_last_msg_id")
    chat_id = data.get("_last_chat_id")
    if msg_id and chat_id:
        try:
            await bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=None
            )
        except Exception:
            pass


async def _save_msg_id(state: FSMContext, msg: Message):
    await state.update_data(_last_msg_id=msg.message_id, _last_chat_id=msg.chat.id)


# ============ MENU HANDLERS ============

@router.callback_query(F.data == "menu_back")
async def menu_back(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    user_name = callback.from_user.first_name or "друг"
    await callback.message.edit_text(
        text=f"👋 {user_name}, выбери действие:",
        reply_markup=await get_main_menu_keyboard(callback.from_user.id)
    )
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


@router.callback_query(F.data == "menu_help")
async def menu_help(callback: CallbackQuery):
    await callback.answer()
    user_name = callback.from_user.first_name or "друг"
    await callback.message.edit_text(
        text=f"👋 Привет, {user_name}!\n\n"
             "📋 <b>Что я умею:</b>\n\n"
             "💸 <b>Добавить трату</b> — записать расход\n"
             "📈 <b>Статус</b> — сколько осталось\n"
             "⚙️ <b>Настройки</b> — изменить бюджет\n\n"
             "Или просто напиши сумму и описание:\n"
             "\"500 кофе\", \"200 такси\" — я сама разберусь! 😊",
        reply_markup=await get_main_menu_keyboard(callback.from_user.id)
    )
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await _cleanup_keyboard(message.bot, message.chat.id)
    telegram_id = message.from_user.id
    user_name = message.from_user.first_name or "друг"

    user = await get_user_or_none(telegram_id)

    if not user:
        await get_or_create_user(
            telegram_id=telegram_id,
            first_name=message.from_user.first_name,
            username=message.from_user.username
        )
        greeting = random.choice(GREETINGS)
        await message.answer(text=greeting)

        sent = await message.answer(
            text="📊 Давай настроим бюджет!\n\n"
                 "Начнём с фундамента: сколько ресурсов у нас в распоряжении на этот месяц?\n"
                 "Чистая математика, никакого осуждения.\n\n"
                 "Введи общую сумму (например: 50000)",
            reply_markup=get_onboarding_keyboard()
        )
        await _save_msg_id(state, sent)
        await state.set_state(BudgetSetup.waiting_for_income)
    else:
        await message.answer(
            text=f"👋 Рад видеть тебя снова, {user_name}!\n\n"
                 "Ты уже настроил свой бюджет. Кубышка и Хотелка в безопасности.\n"
                 "Что хочешь сделать?",
            reply_markup=get_start_choice_keyboard()
        )


@router.callback_query(F.data == "open_menu")
async def open_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    user_name = callback.from_user.first_name or "друг"
    await callback.message.edit_text(
        text=f"👋 {user_name}, выбери действие:",
        reply_markup=await get_main_menu_keyboard(callback.from_user.id)
    )
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


@router.callback_query(F.data == "reset_budget")
async def reset_budget(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()

    await get_or_create_user(
        telegram_id=callback.from_user.id,
        first_name=callback.from_user.first_name,
        username=callback.from_user.username
    )

    await delete_current_budget(callback.from_user.id)

    greeting = random.choice(GREETINGS)
    await callback.message.edit_text(text=greeting)

    sent = await callback.message.answer(
        text="📊 Давай настроим бюджет заново!\n\n"
             "Начнём с фундамента: сколько ресурсов у нас в распоряжении на этот месяц?\n"
             "Чистая математика, никакого осуждения.\n\n"
             "Введи общую сумму (например: 50000)",
        reply_markup=get_onboarding_keyboard()
    )
    await _save_msg_id(state, sent)
    await state.set_state(BudgetSetup.waiting_for_income)


@router.callback_query(F.data == "menu_status")
async def menu_status(callback: CallbackQuery):
    await callback.answer()
    user_name = callback.from_user.first_name or "друг"
    tg_id = callback.from_user.id

    budget = await get_budget_or_none(tg_id)
    if not budget:
        await callback.message.edit_text(
            text=f"👋 Привет, {user_name}!\n\nУ тебя нет бюджета на этот месяц. Нажми /start!",
            reply_markup=await get_main_menu_keyboard(tg_id)
        )
        return

    async with async_session_maker() as session:
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        result = await session.execute(
            select(func.sum(Expense.amount)).where(
                Expense.telegram_id == tg_id,
                Expense.is_deleted == False,
                Expense.date >= today_start
            )
        )
        spent_today = result.scalar() or 0

        result = await session.execute(
            select(func.sum(Expense.amount)).where(
                Expense.telegram_id == tg_id,
                Expense.is_deleted == False,
            )
        )
        spent_period = result.scalar() or 0

    days_left = budget.days_remaining
    dl_base = budget.daily_limit
    savings = budget.black_day_fund

    if budget.free_money > 0:
        money_for_life = budget.free_money - spent_period
        total_budget = budget.free_money
    else:
        money_for_life = budget.total_income - budget.mandatory_payments - budget.black_day_fund - spent_period
        total_budget = budget.total_income

    dl_pred = max(money_for_life / max(days_left, 1), 0) if money_for_life > 0 else 0
    dl_simulated = max((money_for_life + savings) / max(days_left, 1), 0)
    pct_pred = dl_pred / max(dl_base, 1) * 100 if dl_base > 0 else 0
    pct_sim = dl_simulated / max(dl_base, 1) * 100 if dl_base > 0 else 0

    remaining_today = max(dl_base - spent_today, 0)
    remaining_period = money_for_life
    period_end_day = budget._clamped_start
    period_end_str = f"{period_end_day}-го" if period_end_day > 1 else f"{period_end_day}-го"

    end_of_period = days_left <= 3  # Wait, the comment says "менее 3 дней", so <= 2 probably. Let me use the user's definition: Осталось <= 3 дней
    # Actually user says "Осталось <= 3 дней" in section 4, meaning days_left <= 3 for the special mode. Actually, 3 days means "до 3 дней" = up to 3 days = 1, 2, or 3.

    is_critical = money_for_life <= 0 or pct_pred <= 25

    # Build status header
    if remaining_today > 0:
        today_line = f"🟢 <b>Осталось на сегодня:</b> {int(remaining_today)} ₽"
    else:
        today_line = f"🛑 <b>Осталось на сегодня:</b> 0 ₽ (Траты на сегодня стоп!)"

    spent_line = f"📉 <b>Потрачено сегодня:</b> {int(spent_today):,} ₽"
    if spent_today > dl_base:
        spent_line += " 🚨 (Ого, мощный расход!)"

    if remaining_period < 0:
        period_left_line = f"💵 <b>Остаток на жизнь:</b> {int(remaining_period):,} ₽ 💸"
    elif remaining_period > 0:
        period_left_line = f"💵 <b>Остаток на жизнь:</b> {int(remaining_period):,} ₽"
    else:
        period_left_line = f"💵 <b>Остаток на жизнь:</b> 0 ₽ 💸"

    text = (
        f"📊 <b>ФИНАНСОВЫЙ СТАТУС</b>\n\n"
        f"📍 <b>На сегодня:</b>\n"
        f"{today_line}\n"
        f"{spent_line}\n\n"
        f"📅 <b>На период до {period_end_str} (осталось {days_left} дн.)</b>\n"
        f"{period_left_line}\n"
        f"💰 <b>Базовый дневной лимит:</b> {int(dl_base):,} ₽\n"
        f"📥 <b>Всего было (твой бюджет):</b> {int(total_budget):,} ₽\n\n"
        f"🛡️ <b>Твои фонды (под охраной):</b>\n"
        f"📌 <b>Обязательные платежи:</b> {int(budget.mandatory_payments):,} ₽\n"
        f"🏦 <b>Кубышка:</b> {int(budget.black_day_fund):,} ₽\n"
        f"🎯 <b>Хотелка:</b> {int(budget.wishlist_target):,} ₽"
    )

    # Footer zone logic
    if end_of_period:
        if money_for_life <= 0:
            footer = random.choice([
                "Финишная прямая! До конца периода осталось всего ничего. 🏁 Включаем режим супергероя и дотягиваем без новых долгов!",
                "До обнуления периода осталось всего пару дней, но наш кошелек пуст. 🏁 Держимся на морально-волевых, финиш уже виден!",
                "Последние метры дистанции, Бро! Деньги на нуле, но мы обязаны доползти до даты отсечки без новых кредитов. Терпим!",
            ])
            btns = "FRESH_START"
        else:
            footer = random.choice([
                "Осталось всего пару дней до конца периода, а у нас еще есть кэш! 🥳 Бро, мы досрочно победили этот месяц, ты супер-менеджер!",
                "Финишная прямая, а в кармане еще шуршат купюры! 🥳 Горжусь твоей дисциплиной!",
                "Период почти закрыт, а бюджет не пробит! 🥳 Бро, это абсолютная финансовая победа!",
            ])
            btns = "REGULAR"
    elif pct_pred > 80:
        footer = random.choice([
            f"Идем идеально по графику, Бро! 🟩 Твой прогнозный лимит: {int(dl_pred):,} ₽ на день. Твоя внутренняя жаба спокойна!",
            "Бюджет улыбается тебе. 🟩 Все фонды целы, лимит комфортный. Продолжай в том же духе, ты супер-менеджер своей жизни!",
            "Твоя финансовая карма в идеальном порядке. 🟩 Мы четко вписываемся в график, так что сегодня можно позволить себе чуточку больше!",
        ])
        btns = "REGULAR"
    elif pct_pred >= 51:
        footer = random.choice([
            f"Заметил, что мы немного ускорились. 📉 Если продолжим тратить в том же темпе, к концу периода твой дневной лимит сожмется до {int(dl_pred):,} ₽. Давай чуть притормозим, чтобы оставаться в зеленой зоне?",
            f"Бро, мы потихоньку съезжаем с идеального курса. 📉 Прогноз упал до {int(dl_pred):,} ₽ в день. Ситуация полностью под контролем, но давай включим осознанность.",
            f"График трат пополз вниз, Бро. 📉 Прогноз {int(dl_pred):,} ₽ на день — давай удержим эту планку?",
        ])
        btns = "REGULAR"
    elif pct_pred >= 26:
        if pct_sim > 80:
            footer = random.choice([
                f"Уф, Бро, мы катимся вниз. 🎢 Прогноз: лимит сожмется до {int(dl_pred):,} ₽ в день. Включен режим ТУРБО-ЭКОНОМИИ.\n\n💡 Мы можем вернуть всё как было! Если добавим деньги из Кубышки, восстановим лимит до <b>{int(dl_simulated):,} ₽</b> на день и вернемся в зеленую зону!",
                f"Ситуация накаляется. 📉 Лимит упал до {int(dl_pred):,} ₽. Пора затягивать пояса...\n\n💡 Твоя Кубышка может полностью перекрыть этот кризис! Вскрываем заначку? Это подбросит лимит до <b>{int(dl_simulated):,} ₽</b>!",
                f"Мы официально проедаем бюджет быстрее плана. 🎢 Текущий прогноз: {int(dl_pred):,} ₽ на день.\n\n💡 Спасаем положение? Кубышка может поднять лимит до <b>{int(dl_simulated):,} ₽</b>!",
            ])
            btns = "FROM_YELLOW_TO_GREEN"
        elif pct_sim >= 51:
            footer = random.choice([
                f"Уф, Бро, лимит сожмется до {int(dl_pred):,} ₽ в день. 🎢 Включен режим ТУРБО-ЭКОНОМИИ.\n\n💡 Но есть хорошая новость! Твоя Кубышка ({int(savings):,} ₽) может поднять лимит до <b>{int(dl_simulated):,} ₽</b> в день. Вернемся в зеленую зону!",
                f"Мы на грани, лимит зажат до {int(dl_pred):,} ₽. 🎢\n\n💡 План перехвата: Кубышка вытащит нас в безопасную зону. Лимит станет <b>{int(dl_simulated):,} ₽</b> в день!",
                f"Бюджет трещит по швам, лимит {int(dl_pred):,} ₽. 📉\n\n💡 Кубышка готова прийти на помощь! Поднимем планку до <b>{int(dl_simulated):,} ₽</b>!",
            ])
            btns = "FROM_YELLOW_TO_BLUE"
        else:
            footer = random.choice([
                f"Уф, Бро, лимит сожмется до {int(dl_pred):,} ₽ в день. 🎢 Включен режим ТУРБО-ЭКОНОМИИ.",
                f"Включаю режим супер-экономии. 🟨 Прогноз — {int(dl_pred):,} ₽ в день. Постарайся сегодня ничего не покупать!",
                f"До конца периода придется посидеть на гречке. 🟨 Лимит {int(dl_pred):,} ₽ в день. Держимся!",
            ])
            btns = "REGULAR"
    else:
        if pct_sim > 80:
            footer = random.choice([
                f"Бро, мы пробили дно бюджета! 🚨 Прогноз — {int(dl_pred):,} ₽ в день. Это катастрофа.\n\n💡 <b>Но у нас есть супер-план!</b> Кубышка ({int(savings):,} ₽) моментом вытащит нас из ада! Лимит взлетит до <b>{int(dl_simulated):,} ₽</b>!",
                f"Бюджет объявил дефолт. 🟥 Прогноз {int(dl_pred):,} ₽ в день.\n\n💡 <b>Секретное оружие!</b> Кубышка полностью решает проблему. Лимит станет <b>{int(dl_simulated):,} ₽</b>!",
                f"Потратили всё. 🚨 На жизнь {int(dl_pred):,} ₽ в день.\n\n💡 <b>Кубышка спасает!</b> Накопления вернут нас в зеленую зону с лимитом <b>{int(dl_simulated):,} ₽</b>!",
            ])
            btns = "FROM_RED_TO_GREEN"
        elif pct_sim >= 51:
            footer = random.choice([
                f"Бро, мы пробили дно! 🚨 Прогноз {int(dl_pred):,} ₽ в день.\n\n💡 <b>План спасения!</b> Кубышка ({int(savings):,} ₽) поднимет лимит до <b>{int(dl_simulated):,} ₽</b>! Выходим из кризиса в зеленую зону!",
                f"Глубокое финансовое пике. 🟥 Прогноз {int(dl_pred):,} ₽.\n\n💡 <b>Подушка безопасности!</b> Кубышка вытащит нас в стабильную зону с лимитом <b>{int(dl_simulated):,} ₽</b>!",
                f"Критический перерасход! 🚨 Прогноз — {int(dl_pred):,} ₽ в день.\n\n💡 <b>Время вскрывать резервы!</b> Кубышка поднимет дневную норму до <b>{int(dl_simulated):,} ₽</b>!",
            ])
            btns = "FROM_RED_TO_BLUE"
        elif pct_sim >= 26:
            footer = random.choice([
                f"Бро, мы пробили дно! 🚨 Прогноз {int(dl_pred):,} ₽ в день.\n\n💡 <b>План спасения!</b> Кубышка ({int(savings):,} ₽) поднимет лимит до <b>{int(dl_simulated):,} ₽</b>. Выберемся из кризиса в режим экономии.",
                f"Бюджет нажал кнопку катапультирования. 💣 На жизнь {int(dl_pred):,} ₽.\n\n💡 <b>План эвакуации:</b> Кубышка подрастит лимит до <b>{int(dl_simulated):,} ₽</b>. Спасемся от голодовки!",
                f"Мы на самом дне, лимит {int(dl_pred):,} ₽. 🚨\n\n💡 <b>Частичное спасение:</b> Кубышка поднимет лимит до <b>{int(dl_simulated):,} ₽</b>. Лучше, чем ничего!",
            ])
            btns = "FROM_RED_TO_YELLOW"
        else:
            footer = random.choice([
                "Бро, мы пробили дно бюджета! 🚨 Это катастрофа.\n\nНам нужен Тотальный Фреш-Старт, старые цифры больше не работают.",
                "Оу... Дальше ехать некуда. 🟥 Деньги закончились. Давай начнем с чистого листа?",
                "Математика бота больше не бьется с картой. 🚨 Хватит мучить бюджет, давай обнулим этот месяц!",
            ])
            btns = "FRESH_START"

    kb = _build_status_keyboard(btns, tg_id)
    await callback.message.edit_text(
        text=text + "\n\n" + footer,
        reply_markup=kb,
    )


def _build_status_keyboard(btn_type: str, tg_id: int) -> InlineKeyboardMarkup:
    if btn_type == "REGULAR":
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="menu_back")],
        ])
    if btn_type == "FRESH_START":
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Начать с чистого листа", callback_data="trigger_critical_reset")],
            [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="menu_back")],
        ])
    if btn_type == "FROM_YELLOW_TO_GREEN":
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🍏 Вернуть комфорт из Кубышки", callback_data="use_savings")],
            [InlineKeyboardButton(text="💪 Буду экономить", callback_data="menu_back")],
        ])
    if btn_type == "FROM_YELLOW_TO_BLUE":
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🟩 Поднять лимит из Кубышки", callback_data="use_savings")],
            [InlineKeyboardButton(text="💪 Буду экономить", callback_data="menu_back")],
        ])
    if btn_type == "FROM_RED_TO_GREEN":
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Вернуть Зеленую зону из Кубышки", callback_data="use_savings")],
            [InlineKeyboardButton(text="🔄 С чистого листа", callback_data="trigger_critical_reset")],
            [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="menu_back")],
        ])
    if btn_type == "FROM_RED_TO_BLUE":
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Выйти из кризиса в Зеленую зону", callback_data="use_savings")],
            [InlineKeyboardButton(text="🔄 С чистого листа", callback_data="trigger_critical_reset")],
            [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="menu_back")],
        ])
    if btn_type == "FROM_RED_TO_YELLOW":
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚨 Спасти бюджет из Кубышки", callback_data="use_savings")],
            [InlineKeyboardButton(text="🔄 С чистого листа", callback_data="trigger_critical_reset")],
            [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="menu_back")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="menu_back")],
    ])


@router.callback_query(F.data == "use_savings")
async def handle_use_savings(callback: CallbackQuery):
    await callback.answer()
    tg_id = callback.from_user.id
    async with async_session_maker() as session:
        month = datetime.now().strftime("%Y-%m")
        result = await session.execute(
            select(Budget).where(Budget.telegram_id == tg_id, Budget.month == month)
        )
        budget = result.scalar_one_or_none()
        if not budget or budget.black_day_fund <= 0:
            await callback.message.edit_text(
                text="❌ Кубышка пуста. Нечего переносить.",
                reply_markup=await get_main_menu_keyboard(tg_id),
            )
            return
        budget.free_money = (budget.free_money or 0) + budget.black_day_fund
        budget.black_day_fund = 0
        await session.commit()
    await menu_status(callback)


@router.callback_query(F.data == "menu_daily")
async def menu_daily(callback: CallbackQuery):
    await callback.answer()
    user_name = callback.from_user.first_name or "друг"

    user = await get_user_or_none(callback.from_user.id)
    if not user:
        await callback.message.edit_text(
            text=f"👋 {user_name}, у тебя пока нет бюджета. Нажми /start!",
            reply_markup=await get_main_menu_keyboard(callback.from_user.id)
        )
        return

    async with async_session_maker() as session:
        month = datetime.now().strftime("%Y-%m")
        result = await session.execute(
            select(Budget).where(
                Budget.telegram_id == callback.from_user.id,
                Budget.month == month
            )
        )
        budget = result.scalar_one_or_none()
        if not budget:
            await callback.message.edit_text(
                text=f"👋 {user_name}, нет бюджета на этот месяц. Нажми /start!",
                reply_markup=await get_main_menu_keyboard(callback.from_user.id)
            )
            return

        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        result = await session.execute(
            select(func.sum(Expense.amount)).where(
                Expense.telegram_id == callback.from_user.id,
                Expense.is_deleted == False,
                Expense.date >= today_start
            )
        )
        spent_today = result.scalar() or 0

    daily = budget.daily_limit
    remaining = max(daily - spent_today, 0)
    days_left = budget.days_remaining

    if budget.free_money > 0:
        total_line = f"📊 <b>Бюджет на период:</b> {budget.free_money:,.0f}₽"
    else:
        total_line = f"📊 <b>Всего:</b> {budget.total_income:,.0f}₽"

    text = (
        f"💰 <b>Дневной лимит:</b> {daily:,.0f}₽\n"
        f"📉 <b>Потрачено сегодня:</b> {spent_today:,.0f}₽\n"
        f"✅ <b>Осталось на сегодня:</b> {remaining:,.0f}₽\n\n"
        f"📅 <b>Осталось дней:</b> {days_left}\n"
        f"{total_line}\n"
        f"📌 <b>Обязательные:</b> {budget.mandatory_payments:,.0f}₽\n"
        f"🏦 <b>Кубышка:</b> {budget.black_day_fund:,.0f}₽\n"
        f"🎯 <b>Хотелка:</b> {budget.wishlist_target:,.0f}₽"
    )

    await callback.message.edit_text(text=text, reply_markup=await get_main_menu_keyboard(callback.from_user.id))
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


# ============ ONBOARDING / SKIP ============

@router.callback_query(F.data == "skip_step")
async def skip_step(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    current_state = await state.get_state()

    if current_state == BudgetSetup.waiting_for_income.state:
        await state.update_data(income=0, mandatory=0, black_day=0, wishlist_name="", wishlist_price=0)
        await _finish_onboarding(callback, state)
    elif current_state == BudgetSetup.waiting_for_period_start.state:
        await state.update_data(period_start_day=1)
        await _advance_onboarding(callback, state)
    elif current_state == BudgetSetup.waiting_for_mandatory.state:
        await state.update_data(mandatory=0)
        await _advance_onboarding(callback, state)
    elif current_state == BudgetSetup.waiting_for_black_day.state:
        await state.update_data(black_day=0)
        await _advance_onboarding(callback, state)
    elif current_state == BudgetSetup.waiting_for_wishlist_name.state:
        await state.update_data(wishlist_name="", wishlist_price=0)
        await _advance_onboarding(callback, state)
    elif current_state == BudgetSetup.waiting_for_rounding_mode.state:
        await state.update_data(rounding_mode=0)
        await _finish_onboarding(callback, state)
    else:
        await callback.answer()


async def _advance_onboarding(source: CallbackQuery | Message, state: FSMContext):
    current_state = await state.get_state()

    if current_state == BudgetSetup.waiting_for_period_start.state:
        await state.set_state(BudgetSetup.waiting_for_mandatory)
        text = ("✅ Хорошо, период = с 1-го числа.\n\n"
                "Теперь отсечем всё лишнее: аренду, счета и прочую бытовую рутину.\n"
                "Сколько у нас уходит на обязательные платежи?")
        if isinstance(source, CallbackQuery):
            await source.message.edit_text(text=text, reply_markup=get_onboarding_keyboard())
        else:
            await source.answer(text=text, reply_markup=get_onboarding_keyboard())
    elif current_state == BudgetSetup.waiting_for_mandatory.state:
        await state.set_state(BudgetSetup.waiting_for_black_day)
        kw = get_onboarding_keyboard() if isinstance(source, CallbackQuery) else None
        text = "✅ Хорошо.\n\nОк. А теперь давай создадим твою подушку безопасности на случай внезапных приключений.\nСколько будем откладывать в месяц в \"Кубышка\"?"
        if isinstance(source, CallbackQuery):
            await source.message.edit_text(text=text, reply_markup=kw)
        else:
            await source.answer(text=text, reply_markup=get_onboarding_keyboard())
    elif current_state == BudgetSetup.waiting_for_black_day.state:
        await state.set_state(BudgetSetup.waiting_for_wishlist_name)
        text = ("✅ Отлично!\n\n"
                "А теперь о приятном: ради какой большой цели мы всё это затеяли?\n\n"
                "Напиши название и сумму одним сообщением:\n"
                "Например: Ноутбук 50000\n\n"
                "Или нажми «Пропустить»")
        if isinstance(source, CallbackQuery):
            await source.message.edit_text(text=text, reply_markup=get_onboarding_keyboard())
        else:
            await source.answer(text=text, reply_markup=get_onboarding_keyboard())
    elif current_state == BudgetSetup.waiting_for_wishlist_name.state:
        await state.set_state(BudgetSetup.waiting_for_rounding_mode)
        kw = get_rounding_mode_keyboard()
        text = ("✅ Запомнил!\n\n"
                "🐖 Бро, хочешь копить незаметно? Я могу округлять твои траты, "
                "а сдачу закидывать в копилку.\n\n"
                "До какого шага округляем?")
        if isinstance(source, CallbackQuery):
            await source.message.edit_text(text=text, reply_markup=kw)
        else:
            await source.answer(text=text, reply_markup=kw)
    elif current_state == BudgetSetup.waiting_for_rounding_mode.state:
        await state.update_data(rounding_mode=0)
        await _finish_onboarding(source, state)


async def _finish_onboarding(source: CallbackQuery | Message, state: FSMContext):
    data = await state.get_data()
    telegram_id = source.from_user.id if isinstance(source, CallbackQuery) else source.from_user.id

    try:
        await get_or_create_user(
            telegram_id=telegram_id,
            first_name=source.from_user.first_name,
            username=source.from_user.username
        )
    except Exception as e:
        text = "❌ Ошибка базы данных. Попробуй /start ещё раз."
        if isinstance(source, CallbackQuery):
            await source.message.edit_text(text=text)
        else:
            await source.answer(text=text)
        await state.clear()
        return

    month = datetime.now().strftime("%Y-%m")
    wishlist_name = data.get("wishlist_name", "Хотелка") or "Хотелка"
    wishlist_price = data.get("wishlist_price", 0)
    period_start_day = data.get("period_start_day", 1)

    await save_budget(
        telegram_id=telegram_id,
        month=month,
        income=data.get("income", 0),
        mandatory=data.get("mandatory", 0),
        black_day=data.get("black_day", 0),
        wishlist_name=wishlist_name,
        wishlist_price=wishlist_price,
        period_start_day=period_start_day
    )

    rounding_mode = data.get("rounding_mode", 0)
    async with async_session_maker() as session:
        settings_result = await session.execute(
            select(UserSettings).where(UserSettings.telegram_id == telegram_id)
        )
        user_settings = settings_result.scalar_one_or_none()
        if user_settings:
            user_settings.rounding_mode = rounding_mode
        else:
            session.add(UserSettings(telegram_id=telegram_id, rounding_mode=rounding_mode))
        await session.commit()

    import calendar
    today = datetime.now()
    available = data.get("income", 0) - data.get("mandatory", 0) - data.get("black_day", 0)
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    clamped_start = min(period_start_day, days_in_month)
    if clamped_start == 1:
        days_remaining = max(days_in_month - today.day, 0)
    elif today.day >= clamped_start:
        remaining_this = days_in_month - today.day
        days_remaining = remaining_this + clamped_start - 1
    else:
        days_remaining = clamped_start - today.day
    daily_limit = max(available / max(days_remaining, 1), 0)

    user_name = source.from_user.first_name or "друг"

    period_note = f"📅 Период: с {period_start_day}-го числа" if period_start_day != 1 else ""
    text = (f"🎉 <b>Готово!</b> {user_name}!\n\n"
            f"📊 Бюджет на {month}:\n"
            f"• Общий доход: {data.get('income', 0):,.0f}₽\n"
            f"• Обязательные: {data.get('mandatory', 0):,.0f}₽\n"
            f"• Кубышка: {data.get('black_day', 0):,.0f}₽\n"
            f"• Хотелка: {wishlist_price:,.0f}₽\n"
            f"{period_note}\n"
            f"💰 <b>Дневной лимит: {daily_limit:,.0f}₽</b>")

    kb = await get_main_menu_keyboard(telegram_id)
    if isinstance(source, CallbackQuery):
        await source.message.edit_text(text=text, reply_markup=kb)
    else:
        await source.answer(text=text, reply_markup=kb)

    await state.clear()


# ============ BUDGET SETUP STEPS ============

@router.message(BudgetSetup.waiting_for_income)
async def process_income(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
    except ValueError:
        await message.answer("❌ Введи число. Например: 50000")
        return

    await _cleanup_old_buttons(state, message.bot)
    await state.update_data(income=amount)
    await state.set_state(BudgetSetup.waiting_for_period_start)
    sent = await message.answer(
        text="✅ Принял!\n\n"
             "📅 А какого числа у тебя обычно начинается финансовый месяц?\n"
             "(Когда приходит основная зарплата)",
        reply_markup=get_period_start_keyboard()
    )
    await _save_msg_id(state, sent)


@router.callback_query(F.data.in_(["period_today", "period_first", "period_other"]))
async def handle_period_start_choice(callback: CallbackQuery, state: FSMContext):
    import calendar
    today = datetime.now()
    current_state = await state.get_state()

    if callback.data == "period_other":
        await callback.message.edit_text(
            text="✏️ Напиши число (1-31):",
            reply_markup=None
        )
        await callback.answer()
        return

    if callback.data == "period_today":
        day = today.day
    else:  # period_first
        day = 1

    days_in_month = calendar.monthrange(today.year, today.month)[1]
    if day > days_in_month:
        day = days_in_month

    if current_state == BudgetSetup.waiting_for_period_start.state:
        await state.update_data(period_start_day=day)
        await state.set_state(BudgetSetup.waiting_for_mandatory)
        await callback.message.edit_text(
            text="✅ Запомнил!\n\n"
                 "Теперь отсечем всё лишнее: аренду, счета и прочую бытовую рутину.\n"
                 "Сколько у нас уходит на обязательные платежи?",
            reply_markup=get_onboarding_keyboard()
        )
    elif current_state == EditBudget.waiting_for_period_start.state:
        await update_budget_field(callback.from_user.id, "period_start_day", day)
        user_name = callback.from_user.first_name or "друг"
        await callback.message.edit_text(
            text=f"✅ Готово, {user_name}! Период обновлён — с {day}-го числа.",
            reply_markup=await get_main_menu_keyboard(callback.from_user.id)
        )
        await state.clear()

    await callback.answer()


@router.message(BudgetSetup.waiting_for_period_start)
async def process_period_start(message: Message, state: FSMContext):
    import calendar
    today = datetime.now()
    try:
        day = int(message.text.strip())
    except (ValueError, TypeError):
        await message.answer("❌ Введи число. Например: 25")
        return

    if day < 1:
        day = 1
    elif day > 31:
        day = 31

    days_in_month = calendar.monthrange(today.year, today.month)[1]
    if day > days_in_month:
        day = days_in_month

    await _cleanup_old_buttons(state, message.bot)
    await state.update_data(period_start_day=day)
    await state.set_state(BudgetSetup.waiting_for_mandatory)
    sent = await message.answer(
        text="✅ Запомнил!\n\n"
             "Теперь отсечем всё лишнее: аренду, счета и прочую бытовую рутину.\n"
             "Сколько у нас уходит на обязательные платежи?",
        reply_markup=get_onboarding_keyboard()
    )
    await _save_msg_id(state, sent)


@router.message(BudgetSetup.waiting_for_mandatory)
async def process_mandatory(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
    except ValueError:
        await message.answer("❌ Введи число. Например: 15000")
        return

    await _cleanup_old_buttons(state, message.bot)
    await state.update_data(mandatory=amount)
    await state.set_state(BudgetSetup.waiting_for_black_day)
    sent = await message.answer(
        text="✅ Хорошо.\n\n"
             "Ок. А теперь давай создадим твою подушку безопасности на случай внезапных приключений.\n"
             "Сколько будем откладывать в месяц в \"Кубышка\", чтобы ты спал(а) спокойно?",
        reply_markup=get_onboarding_keyboard()
    )
    await _save_msg_id(state, sent)


@router.message(BudgetSetup.waiting_for_black_day)
async def process_black_day(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
    except ValueError:
        await message.answer("❌ Введи число. Например: 5000")
        return

    await _cleanup_old_buttons(state, message.bot)
    await state.update_data(black_day=amount)
    await state.set_state(BudgetSetup.waiting_for_wishlist_name)
    sent = await message.answer(
        text="✅ Отлично!\n\n"
             "А теперь о приятном: ради какой большой цели мы всё это затеяли?\n\n"
             "Напиши название и сумму одним сообщением:\n"
             "Например: Ноутбук 50000\n\n"
             "Или нажми «Пропустить»",
        reply_markup=get_onboarding_keyboard()
    )
    await _save_msg_id(state, sent)


def _parse_wishlist(text: str) -> tuple[str, float]:
    numbers = re.findall(r'[\d ]+', text.replace(',', '.'))
    name = text
    price = 0
    for num_str in numbers:
        try:
            price = float(num_str.replace(" ", ""))
            name = text.replace(num_str, "").strip()
            break
        except:
            continue
    if not name:
        name = "Хотелка"
    elif name[0].islower():
        name = name[0].upper() + name[1:]
    return name, price


@router.message(BudgetSetup.waiting_for_wishlist_name)
async def process_wishlist_name(message: Message, state: FSMContext):
    await _cleanup_old_buttons(state, message.bot)
    name, price = _parse_wishlist(message.text.strip())
    await state.update_data(wishlist_name=name, wishlist_price=price)
    await _advance_onboarding(message, state)


# ============ ROUNDING MODE ============

@router.callback_query(F.data.in_(["rounding_off", "rounding_10", "rounding_100"]))
async def handle_rounding_choice(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    mode_map = {"rounding_off": 0, "rounding_10": 10, "rounding_100": 100}
    mode = mode_map[callback.data]
    current_state = await state.get_state()
    if current_state == BudgetSetup.waiting_for_rounding_mode.state:
        await state.update_data(rounding_mode=mode)
        await _finish_onboarding(callback, state)
    else:
        async with async_session_maker() as session:
            result = await session.execute(
                select(UserSettings).where(UserSettings.telegram_id == callback.from_user.id)
            )
            settings = result.scalar_one_or_none()
            if settings:
                settings.rounding_mode = mode
            else:
                session.add(UserSettings(telegram_id=callback.from_user.id, rounding_mode=mode))
            await session.commit()
        user_name = callback.from_user.first_name or "друг"
        label = "выключено" if mode == 0 else f"{mode} ₽"
        await callback.message.edit_text(
            text=f"✅ Готово, {user_name}! Округление: <b>{label}</b>",
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )


# ============ ADD EXPENSE ============

@router.callback_query(F.data == "menu_add")
async def menu_add(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_name = callback.from_user.first_name or "друг"
    await state.set_state(AddExpense.waiting_for_amount)
    await callback.message.edit_text(
        text=f"💸 Добавить трату, {user_name}!\n\n"
             "Введи сумму и описание:\n"
             "Например: 500 кофе",
        reply_markup=get_cancel_keyboard()
    )
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


@router.message(AddExpense.waiting_for_amount)
async def process_expense(message: Message, state: FSMContext):
    await get_or_create_user(
        telegram_id=message.from_user.id,
        first_name=message.from_user.first_name,
        username=message.from_user.username
    )

    parsed_list = parse_multi_expense_text(message.text.strip())
    if not parsed_list:
        await message.answer("❌ Введи сумму. Например: 500 кофе")
        return

    lines = []
    total_amount = 0
    first_id = None
    errors = 0

    for amount, description in parsed_list:
        if not description:
            description = "трата"
        total_amount += amount

        if description == "трата":
            cat = None
        else:
            try:
                cat, matched = await detect_category_db(description, message.from_user.id)
            except Exception as e:
                logging.error("Category detection failed", exc_info=e)
                cat = None

        cat_id = cat.id if cat else None
        emoji, cat_name = get_category_display(cat.name) if cat else ("📦", "Прочее")

        try:
            async with async_session_maker() as session:
                expense = Expense(
                    telegram_id=message.from_user.id,
                    amount=amount,
                    description=description or cat_name,
                    category_id=cat_id,
                    date=datetime.utcnow()
                )
                session.add(expense)
                await session.commit()
                if first_id is None:
                    first_id = expense.id
        except Exception as e:
            logging.error("Expense insert failed", exc_info=e)
            errors += 1
            continue

        lines.append(f"💰 {amount:,.0f}₽ — {description} {emoji}{cat_name}")

    await state.clear()

    if not lines:
        await message.answer("❌ Ошибка при сохранении трат. Попробуй ещё раз.")
        return

    user_name = message.from_user.first_name or "друг"

    total_round_up = ""
    if total_amount > 0:
        r = await try_apply_round_up(message.from_user.id, total_amount)
        if r:
            total_round_up = r

    await _cleanup_keyboard(message.bot, message.chat.id)

    if len(lines) == 1:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Сменить категорию", callback_data=f"change_cat:{first_id}")],
            [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="menu_back")],
        ])
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="menu_back")],
        ])

    msg = await message.answer(
        text=f"✅ Записано, {user_name}!\n\n" + "\n".join(lines) + total_round_up,
        reply_markup=kb
    )
    _track_keyboard(message.chat.id, msg.message_id)


# ============ CATEGORY CHANGE ============

@router.callback_query(F.data.startswith("change_cat:"))
async def change_category(callback: CallbackQuery):
    await callback.answer()
    expense_id = int(callback.data.split(":")[1])

    categories = await seed_user_categories(callback.from_user.id)

    buttons = []
    row = []
    for i, cat in enumerate(categories):
        emoji, _ = get_category_display(cat.name)
        row.append(InlineKeyboardButton(
            text=f"{emoji} {cat.name}",
            callback_data=f"set_cat:{expense_id}:{cat.id}",
        ))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(
        text="✏️ Новая категория", callback_data=f"new_cat:{expense_id}"
    )])
    buttons.append([InlineKeyboardButton(
        text="⬅️ Назад", callback_data=f"exp_back_cat:{expense_id}"
    )])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(
        text="📂 Выбери категорию:",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("set_cat:"))
async def set_category(callback: CallbackQuery):
    await callback.answer()
    _, expense_id_str, category_id_str = callback.data.split(":")
    expense_id = int(expense_id_str)
    category_id = int(category_id_str)

    async with async_session_maker() as session:
        result = await session.execute(
            select(Expense).where(
                Expense.id == expense_id,
                Expense.telegram_id == callback.from_user.id,
                Expense.is_deleted == False,
            )
        )
        expense = result.scalar_one_or_none()
        if not expense:
            await callback.message.edit_text(
                text="❌ Трата не найдена.",
                reply_markup=await get_main_menu_keyboard(callback.from_user.id),
            )
            return

        result = await session.execute(
            select(Category).where(Category.id == category_id)
        )
        cat = result.scalar_one_or_none()
        if not cat:
            await callback.message.edit_text(
                text="❌ Категория не найдена.",
                reply_markup=await get_main_menu_keyboard(callback.from_user.id),
            )
            return

        expense.category_id = category_id
        await session.commit()

    await add_keyword_to_category(
        callback.from_user.id, category_id, expense.description or "",
    )

    emoji, cat_name = get_category_display(cat.name)
    await callback.message.edit_text(
        text=f"✅ Категория изменена!\n\n"
             f"💰 {expense.amount:,.0f}₽ — {expense.description or cat_name}\n"
             f"{emoji} {cat_name}",
        reply_markup=await get_main_menu_keyboard(callback.from_user.id),
    )


@router.callback_query(F.data.startswith("exp_back_cat:"))
async def back_from_category_change(callback: CallbackQuery):
    await callback.answer()
    user_name = callback.from_user.first_name or "друг"
    await callback.message.edit_text(
        text=f"⬅️ Вернулись, {user_name}!",
        reply_markup=await get_main_menu_keyboard(callback.from_user.id),
    )


@router.callback_query(F.data.startswith("new_cat:"))
async def new_category_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    expense_id = int(callback.data.split(":")[1])
    await state.update_data(new_cat_expense_id=expense_id)
    await state.set_state(CustomCategory.waiting_for_name)
    await callback.message.edit_text(
        text="✏️ Напиши название новой категории:\n\n"
             "Например: Книги, Алкоголь, Животные",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="cancel")],
        ]),
    )


@router.message(CustomCategory.waiting_for_name)
async def save_new_category(message: Message, state: FSMContext):
    name = message.text.strip().capitalize()
    if not name or len(name) > 30:
        await message.answer("❌ Название должно быть от 1 до 30 символов. Попробуй ещё раз:")
        return

    data = await state.get_data()
    expense_id = data.get("new_cat_expense_id")
    if not expense_id:
        await state.clear()
        return

    async with async_session_maker() as session:
        result = await session.execute(
            select(Expense).where(
                Expense.id == expense_id,
                Expense.telegram_id == message.from_user.id,
                Expense.is_deleted == False,
            )
        )
        expense = result.scalar_one_or_none()
        if not expense:
            await message.answer("❌ Трата не найдена.")
            await state.clear()
            return

        cat = Category(
            telegram_id=message.from_user.id,
            name=name,
            keywords=_dump_keywords([clean_and_normalize(expense.description or "")]),
        )
        session.add(cat)
        await session.flush()
        expense.category_id = cat.id
        await session.commit()

    user_name = message.from_user.first_name or "друг"
    await state.clear()
    await _cleanup_keyboard(message.bot, message.chat.id)
    msg = await message.answer(
        text=f"✅ Новая категория «{name}» создана, {user_name}!\n"
             f"Я запомнил слово «{expense.description}» для этой категории.",
        reply_markup=await get_main_menu_keyboard(message.from_user.id),
    )
    _track_keyboard(message.chat.id, msg.message_id)


# ============ OVERDRAFT / MORNING HANDLERS ============

@router.callback_query(F.data.startswith("fix_overdraft:"))
async def handle_fix_overdraft(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    action = parts[1]

    if action == "reduce_limit":
        user_name = callback.from_user.first_name or "друг"
        await callback.message.edit_text(
            text=f"✅ Принято, {user_name}! Остаток месяца проживём с урезанным лимитом. "
                 "Я пересчитал бюджет.",
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )
        return

    overdraft = float(parts[2])
    if action == "wishlist":
        async with async_session_maker() as session:
            result = await session.execute(
                select(Wishlist)
                .where(Wishlist.telegram_id == callback.from_user.id, Wishlist.is_active == True)
                .order_by(Wishlist.id)
                .limit(1)
            )
            goal = result.scalar_one_or_none()
            if goal and goal.current_amount > 0:
                deduction = min(overdraft, goal.current_amount)
                goal.current_amount -= deduction
                await session.commit()
                text = f"🎯 Покрыли {int(deduction)}₽ из Хотелки! Остаток: {int(goal.current_amount)}₽"
            else:
                text = "❌ В Хотелке пока пусто. Попробуй другой вариант."
        await callback.message.edit_text(text=text, reply_markup=await get_main_menu_keyboard(callback.from_user.id))

    elif action == "cubyshka":
        budget = await get_budget_or_none(callback.from_user.id)
        if budget and budget.black_day_fund > 0:
            new_fund = max(budget.black_day_fund - overdraft, 0)
            await update_budget_field(callback.from_user.id, "black_day_fund", new_fund)
            text = f"🆘 Взяли из Кубышки! Остаток в заначке: {int(new_fund)}₽"
        else:
            text = "❌ Кубышка пуста. Попробуй другой вариант."
        await callback.message.edit_text(text=text, reply_markup=await get_main_menu_keyboard(callback.from_user.id))


@router.callback_query(F.data == "trigger_critical_reset")
async def trigger_critical_reset(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(CriticalReset.waiting_for_real_balance)
    msg = await callback.message.answer(
        text="🚀 Окей, забудь про вчерашний кошмар, мы всё обнулили. 👌\n\n"
             "Открой своё банковское приложение и посмотри на баланс.\n"
             "Сколько у тебя прямо сейчас <b>всего денег на карте</b>?\n\n"
             "⚠️ Просто посмотри на общий баланс в приложении банка\n"
             "и введи эту цифру целиком. Дальше я сам разберусь,\n"
             "сколько из этого на жизнь, а сколько — обязательное.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="cancel")],
        ]),
    )
    _track_keyboard(callback.message.chat.id, msg.message_id)


@router.message(CriticalReset.waiting_for_real_balance)
async def save_real_balance(message: Message, state: FSMContext):
    try:
        total_balance = float(message.text.replace(" ", "").replace(",", "."))
        if total_balance < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи число. Например: 50000")
        return

    user_name = message.from_user.first_name or "друг"
    new_limit, days_left, money_for_life, mandatory, cubyshka = await reconcile_budget_with_reality(
        message.from_user.id, total_balance
    )

    await _cleanup_keyboard(message.bot, message.chat.id)

    # 🟢 Зона 1: Всё ок (лимит > 500₽)
    if new_limit > 500:
        await apply_reconciliation(message.from_user.id, money_for_life)
        cubyshka_note = f"\n\n💰 Кстати, твоя Кубышка 🏦 {int(cubyshka)}₽ в полной безопасности, её я не трогал!" if cubyshka > 0 else ""
        await state.clear()
        msg = await message.answer(
            text=f"🚀 Система перезагружена, {user_name}! Старый минус стерт, летим дальше.\n\n"
                 f"💰 Твой новый лимит на сегодня: <b>{int(new_limit)} ₽</b>\n"
                 f"📅 Осталось дней до периода: {days_left}\n"
                 f"📊 Всего денег на жизнь: <b>{int(money_for_life)} ₽</b>"
                 f"{cubyshka_note}",
            reply_markup=await get_main_menu_keyboard(message.from_user.id),
        )
        _track_keyboard(message.chat.id, msg.message_id)
        return

    # 🟡 Зона 2: Турбо-экономия (лимит 100–500₽)
    if new_limit >= 100:
        await apply_reconciliation(message.from_user.id, money_for_life)
        await state.clear()
        msg = await message.answer(
            text=f"Уф, {user_name}, ситуация жесткая. После вычета Кубышки 🏦 {int(cubyshka)}₽ "
                 f"и обязательных 📌 {int(mandatory)}₽ на жизнь остается всего "
                 f"<b>{int(money_for_life)} ₽</b>.\n"
                 f"Твой лимит: <b>{int(new_limit)} ₽</b> в день — это меньше косаря!\n\n"
                 f"🚨 <b>Включаю режим ТУРБО-ЭКОНОМИИ!</b>\n\n"
                 f"Мы либо объявляем хардкорный челлендж и держимся на гречке "
                 f"до 20-го числа, либо ты можешь зайти в настройки и достать "
                 f"немного денег из Кубышки на жизнь.\n\n"
                 f"Что делаем? Принимаешь вызов или идем потрошить Кубышку?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💪 Принимаю вызов!", callback_data="menu_back")],
                [InlineKeyboardButton(text="🏦 Взять из Кубышки", callback_data="edit_black_day")],
            ]),
        )
        _track_keyboard(message.chat.id, msg.message_id)
        return

    # 🔴 Зона 3: Тотальный фреш-старт (лимит < 100₽ или в минусе)
    await state.set_state(FreshStart.waiting_for_mandatory)
    msg = await message.answer(
        text=f"🚨 <b>Бро, это системный сбой!</b>\n\n"
             f"На твоей карте осталось меньше, чем мы отложили "
             f"на Обязательные платежи и Кубышку.\n"
             f"Математика больше не работает. Твой лимит на жизнь: <b>0 ₽</b>.\n\n"
             f"Нам нужен <b>Тотальный Фреш-Старт</b>. Мы обнулим все старые "
             f"планы и ты введёшь новые, честные цифры.\n\n"
             f"Готова пересобрать бюджет за 1 минуту?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Сбросить всё и начать заново", callback_data="fresh_start_begin")],
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="cancel")],
        ]),
    )
    _track_keyboard(message.chat.id, msg.message_id)


# ============ FRESH START (RE-ONBOARDING) ============

@router.callback_query(F.data == "fresh_start_begin")
async def fresh_start_step1(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(FreshStart.waiting_for_mandatory)
    await callback.message.edit_text(
        text="📌 <b>Шаг 1.</b> Давай пересчитаем твои обязательные платежи "
             "(аренда, кредиты, подписки) с сегодняшнего дня и до конца периода.\n\n"
             "Сколько тебе <b>ЕЩЁ</b> предстоит обязательно заплатить "
             "в этом месяце?\n"
             "Если всё уже оплачено, просто напиши <b>0</b>.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="cancel")],
        ]),
    )


@router.message(FreshStart.waiting_for_mandatory)
async def fresh_start_save_mandatory(message: Message, state: FSMContext):
    try:
        mandatory = float(message.text.replace(" ", "").replace(",", "."))
        if mandatory < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи число. Например: 15000")
        return
    await state.update_data(fresh_mandatory=mandatory)
    await state.set_state(FreshStart.waiting_for_black_day)
    await message.answer(
        text="🏦 <b>Шаг 2.</b> Что делаем с Кубышкой?\n\n"
             "Сколько денег ты РЕАЛЬНО готова откладывать "
             "и неприкосновенно хранить прямо сейчас?\n"
             "Если пока нечего — напиши <b>0</b>, "
             "это нормально, сначала выберемся из кризиса.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="cancel")],
        ]),
    )


@router.message(FreshStart.waiting_for_black_day)
async def fresh_start_save_black_day(message: Message, state: FSMContext):
    try:
        cubyshka = float(message.text.replace(" ", "").replace(",", "."))
        if cubyshka < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи число. Например: 5000")
        return
    await state.update_data(fresh_black_day=cubyshka)
    await state.set_state(FreshStart.waiting_for_balance)
    await message.answer(
        text="💰 <b>Шаг 3.</b> И финальный шаг.\n\n"
             "Какая <b>ОБЩАЯ</b> сумма прямо сейчас лежит "
             "на твоей карте? (Какую видишь в приложении банка).",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="cancel")],
        ]),
    )


@router.message(FreshStart.waiting_for_balance)
async def fresh_start_save_balance(message: Message, state: FSMContext):
    try:
        total_balance = float(message.text.replace(" ", "").replace(",", "."))
        if total_balance < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи число. Например: 50000")
        return

    data = await state.get_data()
    new_mandatory = data.get("fresh_mandatory", 0)
    new_cubyshka = data.get("fresh_black_day", 0)

    money_for_life = max(total_balance - new_mandatory - new_cubyshka, 0)
    days_left_budget = await get_budget_or_none(message.from_user.id)
    days_left = days_left_budget.days_remaining if days_left_budget else 1
    if days_left <= 0:
        days_left = 1
    new_limit = max(money_for_life / days_left, 0)

    await apply_reconciliation(
        message.from_user.id,
        free_money=money_for_life,
        new_mandatory=new_mandatory,
        new_black_day=new_cubyshka,
    )

    user_name = message.from_user.first_name or "друг"
    await state.clear()
    await _cleanup_keyboard(message.bot, message.chat.id)

    zone_note = ""
    if new_limit < 100:
        zone_note = "\n\n⚠️ Режим Турбо-экономии включён автоматически — лимит меньше 100₽."
    elif new_limit <= 500:
        zone_note = "\n\n💪 Режим Турбо-экономии включён — лимит меньше 500₽."

    msg = await message.answer(
        text=f"Идеально, {user_name}! Новые настройки применились.\n\n"
             f"📌 {int(new_mandatory)} ₽ — забронировал на оставшиеся обязательные платежи.\n"
             f"🏦 {int(new_cubyshka)} ₽ — упаковал обратно в твою Кубышку.\n"
             f"📊 На жизнь осталось: <b>{int(money_for_life)} ₽</b>.\n"
             f"💰 Твой новый честный лимит на сегодня: <b>{int(new_limit)} ₽</b>."
             f"{zone_note}\n\n"
             f"Держимся, Бро! В этот раз мы справимся! ✊",
        reply_markup=await get_main_menu_keyboard(message.from_user.id),
    )
    _track_keyboard(message.chat.id, msg.message_id)


# ============ SETTINGS ============

@router.callback_query(F.data == "menu_settings")
async def menu_settings(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_name = callback.from_user.first_name or "друг"

    budget = await get_budget_or_none(callback.from_user.id)
    if not budget:
        await callback.message.edit_text(
            text=f"👋 Привет, {user_name}!\nТы ещё не настраивал бюджет. Нажми /start!",
            reply_markup=await get_main_menu_keyboard(callback.from_user.id)
        )
        return

    period_day = budget.period_start_day or 1
    period_info = f"📅 Период: с {period_day}-го" if period_day != 1 else "📅 Период: весь месяц"
    async with async_session_maker() as session:
        settings_result = await session.execute(
            select(UserSettings).where(UserSettings.telegram_id == callback.from_user.id)
        )
        user_settings = settings_result.scalar_one_or_none()
        rounding_label = f"{user_settings.rounding_mode} ₽" if (user_settings and user_settings.rounding_mode > 0) else "выкл"
    if budget.free_money > 0:
        money_line = f"• Свободных: {budget.free_money:,.0f}₽"
    else:
        money_line = f"• Всего доход: {budget.total_income:,.0f}₽"
    await callback.message.edit_text(
        text=f"⚙️ {user_name}, что меняем?\n\n"
             f"📊 Текущий бюджет:\n"
             f"{money_line}\n"
             f"• Обязательные: {budget.mandatory_payments:,.0f}₽\n"
             f"• Кубышка: {budget.black_day_fund:,.0f}₽\n"
             f"• {budget.wishlist_name or 'Хотелка'}: {budget.wishlist_target:,.0f}₽\n"
             f"• Округление: {rounding_label}\n"
             f"{period_info}",
        reply_markup=get_settings_keyboard()
    )
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


@router.callback_query(F.data == "edit_income")
async def edit_income(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(EditBudget.waiting_for_income)
    await callback.message.edit_text(
        text="💰 Введи новую сумму дохода (заменит текущую):",
        reply_markup=get_cancel_keyboard()
    )
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


@router.callback_query(F.data == "add_income")
async def add_income(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(EditBudget.waiting_for_add_income)
    await callback.message.edit_text(
        text="➕ Введи сумму, которую хочешь добавить к текущему доходу:",
        reply_markup=get_cancel_keyboard()
    )
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


@router.callback_query(F.data == "edit_mandatory")
async def edit_mandatory(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(EditBudget.waiting_for_mandatory)
    await callback.message.edit_text(
        text="📌 Введи новую сумму обязательных:",
        reply_markup=get_cancel_keyboard()
    )
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


@router.callback_query(F.data == "edit_black_day")
async def edit_black_day(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(EditBudget.waiting_for_black_day)
    await callback.message.edit_text(
        text="🏦 Введи новую сумму кубышки:",
        reply_markup=get_cancel_keyboard()
    )
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


@router.callback_query(F.data == "edit_wishlist")
async def edit_wishlist(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(EditBudget.waiting_for_wishlist)
    await callback.message.edit_text(
        text="🎯 Введи название и сумму хотелки:\n"
             "Например: Ноутбук 50000",
        reply_markup=get_cancel_keyboard()
    )
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


@router.callback_query(F.data == "edit_period_start")
async def edit_period_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(EditBudget.waiting_for_period_start)
    await callback.message.edit_text(
        text="📅 А какого числа у тебя начинается финансовый месяц?\n"
             "(Когда приходит основная зарплата)",
        reply_markup=get_period_start_keyboard()
    )
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


@router.message(EditBudget.waiting_for_income)
async def save_income(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
        budget = await get_budget_or_none(message.from_user.id)
        if budget and budget.free_money > 0:
            await update_budget_field(message.from_user.id, "free_money", amount)
        else:
            await update_budget_field(message.from_user.id, "total_income", amount)

        await _cleanup_keyboard(message.bot, message.chat.id)
        sent = await message.answer(
            text="✅ Доход обновлён!\n\n"
                 "📅 А какого числа у тебя начинается финансовый месяц?\n"
                 "(Когда приходит основная зарплата)",
            reply_markup=get_period_start_keyboard()
        )
        _track_keyboard(message.chat.id, sent.message_id)
        await state.set_state(EditBudget.waiting_for_period_start)
    except ValueError:
        await message.answer("❌ Введи число. Например: 50000")


@router.message(EditBudget.waiting_for_period_start)
async def save_edit_period_start(message: Message, state: FSMContext):
    import calendar
    today = datetime.now()
    try:
        day = int(message.text.strip())
    except (ValueError, TypeError):
        await message.answer("❌ Введи число. Например: 25")
        return

    if day < 1:
        day = 1
    elif day > 31:
        day = 31

    days_in_month = calendar.monthrange(today.year, today.month)[1]
    if day > days_in_month:
        day = days_in_month

    await update_budget_field(message.from_user.id, "period_start_day", day)
    user_name = message.from_user.first_name or "друг"

    await _cleanup_keyboard(message.bot, message.chat.id)
    msg = await message.answer(
        text=f"✅ Готово, {user_name}! Период обновлён — с {day}-го числа.",
        reply_markup=await get_main_menu_keyboard(message.from_user.id)
    )
    _track_keyboard(message.chat.id, msg.message_id)
    await state.clear()


@router.message(EditBudget.waiting_for_add_income)
async def save_add_income(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
        budget = await get_budget_or_none(message.from_user.id)
        if not budget:
            await message.answer("❌ Сначала настрой бюджет через /start")
            await state.clear()
            return
        if budget.free_money > 0:
            new_total = budget.free_money + amount
            await update_budget_field(message.from_user.id, "free_money", new_total)
        else:
            new_total = budget.total_income + amount
            await update_budget_field(message.from_user.id, "total_income", new_total)
        user_name = message.from_user.first_name or "друг"

        await _cleanup_keyboard(message.bot, message.chat.id)
        msg = await message.answer(
            text=f"✅ Готово, {user_name}! Доход увеличен на {amount:,.0f}₽\n"
                 f"💰 Текущий доход: {new_total:,.0f}₽",
            reply_markup=await get_main_menu_keyboard(message.from_user.id)
        )
        _track_keyboard(message.chat.id, msg.message_id)
        await state.clear()
    except ValueError:
        await message.answer("❌ Введи число. Например: 10000")


@router.message(EditBudget.waiting_for_mandatory)
async def save_mandatory(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
        await update_budget_field(message.from_user.id, "mandatory_payments", amount)
        user_name = message.from_user.first_name or "друг"

        await _cleanup_keyboard(message.bot, message.chat.id)
        msg = await message.answer(
            text=f"✅ Готово, {user_name}! Обязательные: {amount:,.0f}₽",
            reply_markup=await get_main_menu_keyboard(message.from_user.id)
        )
        _track_keyboard(message.chat.id, msg.message_id)
        await state.clear()
    except ValueError:
        await message.answer("❌ Введи число. Например: 15000")


@router.message(EditBudget.waiting_for_black_day)
async def save_black_day(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
        await update_budget_field(message.from_user.id, "black_day_fund", amount)
        user_name = message.from_user.first_name or "друг"

        await _cleanup_keyboard(message.bot, message.chat.id)
        msg = await message.answer(
            text=f"✅ Готово, {user_name}! Кубышка: {amount:,.0f}₽",
            reply_markup=await get_main_menu_keyboard(message.from_user.id)
        )
        _track_keyboard(message.chat.id, msg.message_id)
        await state.clear()
    except ValueError:
        await message.answer("❌ Введи число. Например: 5000")


@router.message(EditBudget.waiting_for_wishlist)
async def save_wishlist(message: Message, state: FSMContext):
    name, price = _parse_wishlist(message.text.strip())

    await update_budget_field(message.from_user.id, "wishlist_name", name)
    await update_budget_field(message.from_user.id, "wishlist_target", price)

    user_name = message.from_user.first_name or "друг"

    await _cleanup_keyboard(message.bot, message.chat.id)
    msg = await message.answer(
        text=f"✅ Готово, {user_name}! Хотелка: {name} — {price:,.0f}₽",
        reply_markup=await get_main_menu_keyboard(message.from_user.id)
    )
    _track_keyboard(message.chat.id, msg.message_id)
    await state.clear()


# ============ ROUNDING MODE SETTINGS ============

@router.callback_query(F.data == "edit_rounding")
async def edit_rounding(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    async with async_session_maker() as session:
        result = await session.execute(
            select(UserSettings).where(UserSettings.telegram_id == callback.from_user.id)
        )
        settings = result.scalar_one_or_none()
        current = settings.rounding_mode if settings else 0

    label = "выключено" if current == 0 else f"{current} ₽"
    await callback.message.edit_text(
        text=f"🐖 Сейчас округление: <b>{label}</b>\n\n"
             "Мне округлять твои траты, а сдачу закидывать в копилку?",
        reply_markup=get_rounding_mode_keyboard(),
    )
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


# ============ CANCEL / BACK ============

@router.callback_query(F.data == "cancel")
async def cancel(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    current_state = await state.get_state()
    await state.clear()

    if current_state and (
        current_state.startswith("CriticalReset.") or
        current_state.startswith("FreshStart.")
    ):
        await callback.message.delete()
        return

    user_name = callback.from_user.first_name or "друг"
    await callback.message.edit_text(
        text=f"⬅️ Вернулись, {user_name}!",
        reply_markup=await get_main_menu_keyboard(callback.from_user.id)
    )
    _track_keyboard(callback.message.chat.id, callback.message.message_id)


# ============ UNSUPPORTED CONTENT ============

@router.message(F.voice)
async def handle_voice(message: Message):
    await message.answer(
        "🎤 Я не умею обрабатывать голосовые сообщения.\n"
        "Напиши сумму и описание текстом, например: 500 кофе"
    )


@router.message(F.photo | F.video | F.document | F.sticker | F.animation)
async def handle_media(message: Message):
    await message.answer(
        "📎 Я понимаю только текстовые сообщения.\n"
        "Напиши сумму и описание, например: 500 кофе"
    )


# ============ TEXT INPUT (free form) ============

@router.message()
async def handle_text(message: Message, state: FSMContext):
    text = message.text.strip()

    if text.startswith('/'):
        return

    menu_keywords = {"меню", "помощь", "настройки", "статус", "история", "назад", "отмена"}
    if text.lower() in menu_keywords:
        user_name = message.from_user.first_name or "друг"
        await _cleanup_keyboard(message.bot, message.chat.id)
        msg = await message.answer(
            text=f"👋 {user_name}, воспользуйся кнопками в меню!",
            reply_markup=await get_main_menu_keyboard(message.from_user.id)
        )
        _track_keyboard(message.chat.id, msg.message_id)
        return

    parsed_list = parse_multi_expense_text(text)
    if parsed_list:
        await get_or_create_user(
            telegram_id=message.from_user.id,
            first_name=message.from_user.first_name,
            username=message.from_user.username
        )

        lines = []
        total_amount = 0
        first_id = None

        for amount, description in parsed_list:
            if not description:
                description = "трата"
            total_amount += amount

            if description == "трата":
                cat = None
            else:
                try:
                    cat, matched = await detect_category_db(description, message.from_user.id)
                except Exception as e:
                    logging.error("Category detection failed", exc_info=e)
                    cat = None

            cat_id = cat.id if cat else None
            emoji, cat_name = get_category_display(cat.name) if cat else ("📦", "Прочее")

            try:
                async with async_session_maker() as session:
                    expense = Expense(
                        telegram_id=message.from_user.id,
                        amount=amount,
                        description=description or cat_name,
                        category_id=cat_id,
                        date=datetime.utcnow()
                    )
                    session.add(expense)
                    await session.commit()
                    if first_id is None:
                        first_id = expense.id
            except Exception as e:
                logging.error("Expense insert failed (free-form)", exc_info=e)
                cause = getattr(e, "__cause__", None)
                if cause:
                    logging.error("Caused by: %s: %s", type(cause).__name__, cause)
                continue

            lines.append(f"💰 {amount:,.0f}₽ — {description} {emoji}{cat_name}")

        if not lines:
            await message.answer("❌ Ошибка при сохранении трат. Попробуй ещё раз.")
            return

        user_name = message.from_user.first_name or "друг"

        total_round_up = ""
        if total_amount > 0:
            r = await try_apply_round_up(message.from_user.id, total_amount)
            if r:
                total_round_up = r

        await _cleanup_keyboard(message.bot, message.chat.id)

        if len(lines) == 1:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✏️ Сменить категорию", callback_data=f"change_cat:{first_id}")],
                [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="menu_back")],
            ])
        else:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="menu_back")],
            ])

        msg = await message.answer(
            text=f"✅ Записано, {user_name}!\n\n" + "\n".join(lines) + total_round_up,
            reply_markup=kb
        )
        _track_keyboard(message.chat.id, msg.message_id)
        return

    user_name = message.from_user.first_name or "друг"

    await _cleanup_keyboard(message.bot, message.chat.id)
    msg = await message.answer(
        text=f"👋 {user_name}, не поняла...\n\n"
             "Напиши сумму и описание, например:\n"
             "\"500 кофе\" или нажми кнопку в меню",
        reply_markup=await get_main_menu_keyboard(message.from_user.id)
    )
    _track_keyboard(message.chat.id, msg.message_id)
