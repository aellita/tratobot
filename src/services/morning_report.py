import random
import logging
import asyncio

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select

from ..db.database import async_session_maker
from ..db.models.models import User, UserSettings
from .expense_service import get_yesterday_expenses_sum, get_today_daily_limit
from .budget_service import get_days_remaining

logger = logging.getLogger(__name__)


def get_morning_keyboard(overdraft: float) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 Покрыть из Мечты", callback_data=f"fix_overdraft:wishlist:{overdraft}")],
        [InlineKeyboardButton(text="🆘 Взять из Кубышки", callback_data=f"fix_overdraft:cubyshka:{overdraft}")],
        [InlineKeyboardButton(text="📉 Урезать лимит на месяц", callback_data="fix_overdraft:reduce_limit")],
    ])


def get_critical_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 С чистого листа (Ревизия)", callback_data="trigger_critical_reset")],
        [InlineKeyboardButton(text="📉 Урезать лимит на месяц", callback_data="fix_overdraft:reduce_limit")],
    ])


def get_morning_message(overdraft_percent: float, new_limit: float) -> str:
    if overdraft_percent <= 20:
        return random.choice([
            f"☕️ Утречко! Вчера слегка вышли за рамки (на {int(overdraft_percent)}%). Ничего страшного, бюджет пересчитан. Твой чистый лимит на сегодня: <b>{int(new_limit)} ₽</b>.",
            f"☀️ Доброе утро! Вчерашний день слегка покусал наши планы (овердрафт {int(overdraft_percent)}%). Я раскидал этот минус по остатку месяца. Сегодня гуляем на <b>{int(new_limit)} ₽</b>.",
        ])
    elif overdraft_percent <= 100:
        return (
            f"⚠️ Бро, утренний разбор полетов. Вчера мы превысили лимит на <b>{int(overdraft_percent)}%</b>. "
            f"Если просто уменьшить лимит на сегодня, кошелек сильно похудеет. "
            f"Спасаем положение за счет Кубышки/Мечты или затягиваем пояса?"
        )
    else:
        return (
            f"🚨 Оу... Вчерашние траты превысили наш лимит на <b>{int(overdraft_percent)}%</b>! Мы официально на мели. "
            f"Если продолжим в том же духе, придется месяц питаться воздухом. "
            f"Давай распечатаем заначку и начнем с чистого листа?"
        )


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
                new_limit = daily_limit
                await bot.send_message(
                    tg_id,
                    f"☀️ Доброе утро, бро! Вчера мы красавчики, уложились в лимит.\n"
                    f"На сегодня у нас есть <b>{int(new_limit)} ₽</b>. Держим темп!"
                )
                await asyncio.sleep(0.05)
                continue

            overdraft = yesterday_spent - daily_limit
            overdraft_percent = (overdraft / daily_limit) * 100

            new_limit = daily_limit
            text = get_morning_message(overdraft_percent, new_limit)

            if overdraft_percent <= 20:
                await bot.send_message(tg_id, text)
            elif overdraft_percent <= 100:
                await bot.send_message(tg_id, text, reply_markup=get_morning_keyboard(overdraft))
            else:
                await bot.send_message(tg_id, text, reply_markup=get_critical_keyboard())

            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Ошибка утреннего отчёта {tg_id}: {e}")

    logger.info("Утренняя рассылка завершена.")
