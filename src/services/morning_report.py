import random
import logging
import asyncio
from datetime import datetime

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select

from ..db.database import async_session_maker
from ..db.models.models import User, UserSettings, Budget, Wishlist
from .expense_service import get_yesterday_expenses_sum, get_today_daily_limit
from .budget_service import get_days_remaining

logger = logging.getLogger(__name__)


async def _get_morning_scenario(tg_id: int, overdraft: float, daily_limit: float) -> tuple[str, InlineKeyboardMarkup | None, str]:
    overdraft_percent = (overdraft / daily_limit) * 100

    if overdraft_percent <= 20:
        text = random.choice([
            f"☀️ Утречко! Вчера слегка вышли за рамки (на {int(overdraft)}₽). Ничего страшного, бюджет пересчитан. Твой чистый лимит на сегодня: <b>{int(daily_limit)} ₽</b>.",
            f"☀️ Доброе утро! Вчерашний день слегка покусал наши планы (на {int(overdraft)}₽). Я раскидал этот минус по остатку месяца. Сегодня гуляем на <b>{int(daily_limit)} ₽</b>.",
        ])
        return text, None, ""

    async with async_session_maker() as session:
        budget_result = await session.execute(
            select(Budget).where(
                Budget.telegram_id == tg_id,
                Budget.month == datetime.now().strftime("%Y-%m"),
            )
        )
        budget = budget_result.scalar_one_or_none()
        cubyshka = budget.black_day_fund if budget else 0

        goal_result = await session.execute(
            select(Wishlist.current_amount)
            .where(Wishlist.telegram_id == tg_id, Wishlist.is_active == True)
            .order_by(Wishlist.id)
            .limit(1)
        )
        goal_amount = float(goal_result.scalar() or 0.0)

        goal_name = budget.wishlist_name if budget else "Хотелка"
        days_left = budget.days_remaining if budget else 1

    has_cubyshka = cubyshka > 0
    has_goal = goal_amount > 0

    if overdraft > daily_limit:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 С чистого листа (Ревизия)", callback_data="trigger_critical_reset")],
            [InlineKeyboardButton(text="📉 Урезать лимит на месяц", callback_data="fix_overdraft:reduce_limit")],
        ])
        text = random.choice([
            f"🚨 Оу... Вчерашние траты превысили наш лимит на <b>{int(overdraft_percent)}%</b>! "
            f"Мы официально на мели. Если продолжим в том же духе, придётся месяц питаться воздухом. "
            f"Давай распечатаем заначку и начнём с чистого листа?",

            f"💥 <b>Критический перерасход:</b>\nВчера мы пробили дно — минус <b>{int(overdraft)} ₽</b> к лимиту. "
            f"Такими темпами к концу периода нас ждёт только гречка и вода. "
            f"Время принимать жёсткие решения. Выбирай:",
        ])
        return text, kb, "D"

    if has_cubyshka and has_goal:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎯 Покрыть из Хотелки", callback_data=f"fix_overdraft:wishlist:{overdraft}")],
            [InlineKeyboardButton(text="🆘 Взять из Кубышки", callback_data=f"fix_overdraft:cubyshka:{overdraft}")],
            [InlineKeyboardButton(text="📉 Урезать лимит на месяц", callback_data="fix_overdraft:reduce_limit")],
        ])
        text = f"☀️ Утречко! Вчера мы превысили лимит на <b>{int(overdraft)} ₽</b>. " \
               f"Найти клад под подушкой — план хороший, но у нас есть варианты полегче. " \
               f"Выбирай, откуда спишем вчерашнее веселье, и я выдам тебе чистый лимит на сегодня:"
        return text, kb, "A"

    if has_goal:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎯 Покрыть из Хотелки", callback_data=f"fix_overdraft:wishlist:{overdraft}")],
            [InlineKeyboardButton(text="📉 Урезать лимит на месяц", callback_data="fix_overdraft:reduce_limit")],
        ])
        text = f"☕️ Доброе утро, бро! Вчерашние траты оставили нам хвостик в <b>-{int(overdraft)} ₽</b>. " \
               f"Наша Кубышка пуста, так что спасать положение придётся либо за счёт накоплений на «{goal_name}», " \
               f"либо затянув пояса до конца периода. Твой ход:"
        return text, kb, "B"

    if has_cubyshka:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🆘 Взять из Кубышки", callback_data=f"fix_overdraft:cubyshka:{overdraft}")],
            [InlineKeyboardButton(text="📉 Урезать лимит на месяц", callback_data="fix_overdraft:reduce_limit")],
        ])
        text = f"👋 Привет! Твой кошелёк просил передать, что вчера ему было больно на <b>{int(overdraft)} ₽</b>. " \
               f"На хотелки мы ещё ничего не скопили, так что выбор небольшой: распечатываем Кубышку " \
               f"или принудительно худеем по лимитам на оставшиеся {days_left} дней. Что делаем?"
        return text, kb, "V"

    # Neither has money
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📉 Изменить лимит (Урезать)", callback_data="fix_overdraft:reduce_limit")],
    ])
    text = f"🚨 Так, бро. Вчера зафиксирован овердрафт на <b>{int(overdraft)} ₽</b>, а на балансах у нас по нулям. " \
           f"Кубышка пуста, на хотелку ничего нет. Сейчас остаётся только жестко урезать дневной лимит. " \
           f"Но если найдёшь деньги под подушкой, добавь их через кнопку \"➕ Добавить доход\" в настройках, и мы вздохнём свободнее!"
    return text, kb, "G"


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

            daily_limit = await get_today_daily_limit(tg_id)
            if daily_limit <= 0:
                continue

            yesterday_spent = await get_yesterday_expenses_sum(tg_id)

            if yesterday_spent <= daily_limit:
                menu_kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="open_menu")],
                ])
                await bot.send_message(
                    tg_id,
                    f"☀️ Доброе утро, бро! Вчера мы красавчики, уложились в лимит.\n"
                    f"На сегодня у нас есть <b>{int(daily_limit)} ₽</b>. Держим темп!",
                    reply_markup=menu_kb,
                )
                await asyncio.sleep(0.05)
                continue

            overdraft = yesterday_spent - daily_limit
            text, kb, scenario = await _get_morning_scenario(tg_id, overdraft, daily_limit)

            if kb:
                await bot.send_message(tg_id, text, reply_markup=kb)
            else:
                menu_kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="open_menu")],
                ])
                await bot.send_message(tg_id, text, reply_markup=menu_kb)

            logger.info(f"Утренний отчёт {tg_id}: сценарий {scenario}, овердрафт {int(overdraft)}₽")

            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Ошибка утреннего отчёта {tg_id}: {e}")

    logger.info("Утренняя рассылка завершена.")
