import random
import logging
import asyncio
from datetime import datetime

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select

from ..db.database import async_session_maker
from ..db.models.models import User, UserSettings, Budget
from .expense_service import get_yesterday_expenses_sum, get_current_period_expenses_sum

logger = logging.getLogger(__name__)


def _build_morning_keyboard(btn_type: str) -> InlineKeyboardMarkup:
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


async def send_morning_reports(bot: Bot):
    logger.info("Запуск утренней рассылки в 08:00...")

    async with async_session_maker() as session:
        result = await session.execute(select(User.telegram_id))
        user_ids = result.scalars().all()

    for tg_id in user_ids:
        try:
            async with async_session_maker() as session:
                settings_result = await session.execute(
                    select(UserSettings).where(UserSettings.telegram_id == tg_id)
                )
                settings = settings_result.scalar_one_or_none()
                if settings and not settings.notifications_enabled:
                    continue

            from .budget_service import get_active_budget
            budget = await get_active_budget(tg_id)

            if not budget or budget.daily_limit <= 0:
                continue

            yesterday_spent = await get_yesterday_expenses_sum(tg_id)
            spent_period = await get_current_period_expenses_sum(tg_id)

            days_left = budget.days_remaining
            dl_base = budget.daily_limit
            savings = budget.black_day_fund

            if budget.free_money > 0:
                money_for_life = budget.free_money - spent_period
            else:
                money_for_life = budget.total_income - budget.mandatory_payments - budget.black_day_fund - spent_period

            dl_pred = max(money_for_life / max(days_left, 1), 0) if money_for_life > 0 else 0
            dl_simulated = max((money_for_life + savings) / max(days_left, 1), 0)
            pct_pred = dl_pred / max(dl_base, 1) * 100 if dl_base > 0 else 0
            pct_sim = dl_simulated / max(dl_base, 1) * 100 if dl_base > 0 else 0

            end_of_period = days_left <= 3

            overdraft = max(yesterday_spent - dl_base, 0)
            if yesterday_spent <= dl_base:
                yesterday_line = (
                    f"📅 <b>Вчера:</b> потрачено {int(yesterday_spent):,} ₽ из {int(dl_base):,} ₽ ✅"
                )
            else:
                yesterday_line = (
                    f"📅 <b>Вчера:</b> потрачено {int(yesterday_spent):,} ₽ "
                    f"из {int(dl_base):,} ₽ — перерасход <b>{int(overdraft):,} ₽</b> 🚨"
                )

            if end_of_period:
                if money_for_life <= 0:
                    zone = "END_EMPTY"
                    btn_type = "FRESH_START"
                else:
                    zone = "END_OK"
                    btn_type = "REGULAR"
            elif pct_pred > 80:
                zone = "GREEN"
                btn_type = "REGULAR"
            elif pct_pred >= 51:
                zone = "YELLOW_LIGHT"
                btn_type = "REGULAR"
            elif pct_pred >= 26:
                if pct_sim > 80:
                    zone = "YELLOW_SIM_GREEN"
                    btn_type = "FROM_YELLOW_TO_GREEN"
                elif pct_sim >= 51:
                    zone = "YELLOW_SIM_BLUE"
                    btn_type = "FROM_YELLOW_TO_BLUE"
                else:
                    zone = "YELLOW_SIM_NONE"
                    btn_type = "REGULAR"
            else:
                if pct_sim > 80:
                    zone = "RED_SIM_GREEN"
                    btn_type = "FROM_RED_TO_GREEN"
                elif pct_sim >= 51:
                    zone = "RED_SIM_BLUE"
                    btn_type = "FROM_RED_TO_BLUE"
                elif pct_sim >= 26:
                    zone = "RED_SIM_YELLOW"
                    btn_type = "FROM_RED_TO_YELLOW"
                else:
                    zone = "RED_DEAD"
                    btn_type = "FRESH_START"

            if zone == "END_EMPTY":
                zone_text = random.choice([
                    f"Финишная прямая, но деньги на нуле. 🏁 Осталось {days_left} дн. Держимся на морально-волевых!",
                    f"До конца периода {days_left} дн., кэш закончился. 💪 Терпим, бро, финиш уже виден!",
                ])
            elif zone == "END_OK":
                zone_text = random.choice([
                    f"Осталось {days_left} дн. до конца периода, а у нас ещё {int(money_for_life):,} ₽! 🥳 Отличный финиш!",
                    f"Финишная прямая с деньгами в кармане! 🥳 До конца периода {days_left} дн., остаток {int(money_for_life):,} ₽.",
                ])
            elif zone == "GREEN":
                zone_text = random.choice([
                    f"🟩 Всё по плану! Прогнозный лимит: {int(dl_pred):,} ₽/день. Продолжаем в том же духе!",
                    f"🟩 Идём идеально по графику. Прогноз: {int(dl_pred):,} ₽/день.",
                ])
            elif zone == "YELLOW_LIGHT":
                zone_text = random.choice([
                    f"📉 Мы потихоньку отстаём от графика. Прогноз: {int(dl_pred):,} ₽/день. Давай чуть притормозим?",
                    f"📉 Прогнозный лимит снизился до {int(dl_pred):,} ₽/день. Включаем осознанность!",
                ])
            elif zone == "YELLOW_SIM_GREEN":
                zone_text = random.choice([
                    f"🟨 Режим турбо-экономии! Прогноз: {int(dl_pred):,} ₽/день.\n"
                    f"💡 Кубышка ({int(savings):,} ₽) вернёт нас в зелёную зону — лимит будет {int(dl_simulated):,} ₽/день!",
                    f"🟨 Затягиваем пояса — прогноз {int(dl_pred):,} ₽/день.\n"
                    f"💡 Вскрываем Кубышку? Это подбросит лимит до {int(dl_simulated):,} ₽/день!",
                ])
            elif zone == "YELLOW_SIM_BLUE":
                zone_text = random.choice([
                    f"🟨 Режим турбо-экономии! Прогноз: {int(dl_pred):,} ₽/день.\n"
                    f"💡 Кубышка поднимет лимит до <b>{int(dl_simulated):,} ₽</b>/день.",
                    f"🟨 Бюджет трещит по швам, прогноз {int(dl_pred):,} ₽/день.\n"
                    f"💡 Кубышка готова помочь — поднимем планку до {int(dl_simulated):,} ₽/день!",
                ])
            elif zone == "YELLOW_SIM_NONE":
                zone_text = random.choice([
                    f"🟨 Режим турбо-экономии. Прогноз: {int(dl_pred):,} ₽/день. Держимся!",
                    f"🟨 Включаю режим супер-экономии. Прогноз {int(dl_pred):,} ₽/день.",
                ])
            elif zone == "RED_SIM_GREEN":
                zone_text = random.choice([
                    f"🔴 Мы на дне! Прогноз: {int(dl_pred):,} ₽/день.\n"
                    f"💡 Кубышка ({int(savings):,} ₽) моментом вытащит нас! Лимит взлетит до <b>{int(dl_simulated):,} ₽</b>/день!",
                    f"🔴 Критическая ситуация: {int(dl_pred):,} ₽/день.\n"
                    f"💡 Секретное оружие — Кубышка! Лимит станет {int(dl_simulated):,} ₽/день!",
                ])
            elif zone == "RED_SIM_BLUE":
                zone_text = random.choice([
                    f"🔴 Глубокое пике. Прогноз: {int(dl_pred):,} ₽/день.\n"
                    f"💡 Кубышка вытащит нас в стабильную зону: {int(dl_simulated):,} ₽/день!",
                    f"🔴 Бюджет на минимуме — {int(dl_pred):,} ₽/день.\n"
                    f"💡 Время вскрывать резервы! Кубышка поднимет лимит до {int(dl_simulated):,} ₽/день!",
                ])
            elif zone == "RED_SIM_YELLOW":
                zone_text = random.choice([
                    f"🔴 Мы на дне. Прогноз: {int(dl_pred):,} ₽/день.\n"
                    f"💡 Кубышка ({int(savings):,} ₽) подрастит лимит до {int(dl_simulated):,} ₽/день.",
                    f"🔴 Денег почти не осталось — {int(dl_pred):,} ₽/день.\n"
                    f"💡 Кубышка смягчит падение: лимит будет {int(dl_simulated):,} ₽/день.",
                ])
            else:
                zone_text = random.choice([
                    "🔴 Мы пробили дно. Денег нет. 🚀 Нужен фреш-старт.",
                    "🔴 Катастрофа! Бюджет исчерпан. Пора начинать с чистого листа.",
                ])

            full_text = (
                f"☀️ Доброе утро, бро!\n\n"
                f"{yesterday_line}\n\n"
                f"{zone_text}"
            )

            kb = _build_morning_keyboard(btn_type)
            await bot.send_message(tg_id, full_text, reply_markup=kb)

            logger.info(f"Утренний отчёт отправлен {tg_id} (зона {zone})")

            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Ошибка утреннего отчёта {tg_id}: {e}")

    logger.info("Утренняя рассылка завершена.")
