import random
import logging
import asyncio
from datetime import datetime

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select

from ..db.database import async_session_maker
from ..db.models.models import User, UserSettings, Budget
from .expense_service import get_today_expenses_sum, get_today_daily_limit, get_current_period_expenses_sum

logger = logging.getLogger(__name__)

_reported_today: set[int] = set()


def clear_reported_set():
    _reported_today.clear()


def get_evening_message(limit: float, spent: float, available_cash: float, days_left: int, wishlist_name: str) -> str:
    if spent <= limit:
        saved = limit - spent
        if int(spent) == 0:
            green_phrases = [
                f"🔋 <b>Вечерний итог:</b>\nБро, сегодня трат не было! Лимит {int(limit)}₽ — целёхонек. "
                f"Если сегодня всё-таки были расходы и ты забыл(а) их записать, допиши прямо сейчас — я пересчитаю! 📝",

                f"🌟 <b>День без трат?</b>\nХм, интересно. Либо ты сегодня непривычно frugal, либо забыл что-то внести. "
                f"Напоминаю: траты можно дописывать в любой момент обычным сообщением.",

                f"💎 <b>Финансовый отчёт:</b>\nЗа день потрачено 0₽. Если это ошибка и ты что-то упустил(а) — "
                f"просто напиши мне сумму, я обновлю отчёт и пересчитаю прогноз!",
            ]
        else:
            green_phrases = [
                f"🔋 <b>Вечерний итог:</b>\nБро, ты сегодня просто машина! Твой лимит был {int(limit)}₽, а потратил ты всего {int(spent)}₽. Сэкономленные <b>{int(saved)}₽</b> я мысленно откладываю в счет твоей Хотелки. Спи спокойно, день закрыт в плюс! 🥳",
                f"🌟 <b>Управленческий триумф!</b>\nПотрачено всего {int(spent)}₽ из {int(limit)}₽. Ты удержал баланс, а это значит, что мы на один шаг ближе к твоим целям. Горжусь тобой, иди отдыхай! 🤜🤛",
                f"💎 <b>Финансовый флекс:</b>\nСегодня мы не спустили деньги на ветер. Лимит: {int(limit)}₽, факт: {int(spent)}₽. Кубышка довольно урчит, а Хотелка становится ближе. Ложись спать с чистой совестью! 💤",
                f"🧘 <b>Дзен в кошельке:</b>\n{int(spent)}₽ потрачено, {int(saved)}₽ спасено. Ты контролируешь свои деньги, а не они тебя. Отличный день, бро. Завтра продолжим в том же духе!",
            ]
        return random.choice(green_phrases)

    overdraft = spent - limit
    days_to_grease = int(available_cash / overdraft) if overdraft > 0 else days_left
    days_to_grease = max(1, min(days_to_grease, days_left))
    wishlist_delay = max(1, int(overdraft / limit)) if limit > 0 else 1

    evening_phrases = [
        f"👀 <b>Ночной аудит:</b>\nСегодня мы перебрали на <b>{int(overdraft)} ₽</b>. Математика штука упрямая: если продолжим в том же духе, перейдём на гречку и воду уже через <b>{days_to_grease} дн.</b> Отдыхай, завтра придумаем, как вырулить! 🔧",

        f"🔋 <b>Вечерний аудит:</b>\nСегодня мы шиканули на лишние <b>{int(overdraft)} ₽</b>. Это не катастрофа, но «{wishlist_name}» отодвинулась примерно на <b>{wishlist_delay} дн.</b> назад в будущее. 🗺 Убираю калькулятор, ложись спать, утро вечера мудренее.",

        f"📊 <b>Фиксирую дневной овердрафт:</b>\nМы вышли за край на <b>{int(overdraft)} ₽</b>. Если не сбавим обороты, последние <b>{min(5, days_left)} дн.</b> до зарплаты придётся провести в режиме супер-эконома. Закрывай банковские приложения, на сегодня финансовые игры окончены. Спокойной ночи! 🌙",
    ]
    return random.choice(evening_phrases)


async def send_evening_teaser(bot: Bot):
    logger.info("Запуск вечернего тизера в 22:00...")

    async with async_session_maker() as session:
        result = await session.execute(select(User.telegram_id))
        user_ids = result.scalars().all()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏁 Показать отчет", callback_data="generate_evening_report")],
    ])

    for tg_id in user_ids:
        try:
            async with async_session_maker() as session:
                settings_result = await session.execute(
                    select(UserSettings).where(UserSettings.telegram_id == tg_id)
                )
                settings = settings_result.scalar_one_or_none()
                if settings and not settings.notifications_enabled:
                    continue

            limit = await get_today_daily_limit(tg_id)
            if limit <= 0:
                continue

            await bot.send_message(
                chat_id=tg_id,
                text="👁 Псс, день подходит к концу!\n\n"
                     "Твой вечерний отчет по тратам уже готов. Если забыл что-то внести "
                     "(например, ту самую чистку или аптеку), допиши прямо сейчас обычным сообщением.\n\n"
                     "Если всё внесено — жми кнопку ниже, подведем итоги! 📊",
                reply_markup=keyboard,
            )
            logger.info(f"Тизер отправлен {tg_id}")
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Не удалось отправить тизер для {tg_id}: {e}")

    logger.info("Рассылка тизеров завершена.")


async def send_actual_report(tg_id: int, bot: Bot) -> bool:
    try:
        async with async_session_maker() as session:
            settings_result = await session.execute(
                select(UserSettings).where(UserSettings.telegram_id == tg_id)
            )
            settings = settings_result.scalar_one_or_none()
            if settings and not settings.notifications_enabled:
                return False

            budget_result = await session.execute(
                select(Budget).where(
                    Budget.telegram_id == tg_id,
                    Budget.month == datetime.now().strftime("%Y-%m"),
                )
            )
            budget = budget_result.scalar_one_or_none()

        limit = await get_today_daily_limit(tg_id)
        if limit <= 0:
            return False

        spent = await get_today_expenses_sum(tg_id)

        if budget:
            days_left = budget.days_remaining
            if budget.free_money > 0:
                total_available = budget.free_money
            else:
                total_available = budget.total_income - budget.mandatory_payments - budget.black_day_fund
            period_spent = await get_current_period_expenses_sum(tg_id)
            available_cash = max(total_available - period_spent, 0)
            wishlist_name = budget.wishlist_name or "Хотелка"
        else:
            days_left = 1
            available_cash = 0
            wishlist_name = "Хотелка"

        text = get_evening_message(
            limit=limit,
            spent=spent,
            available_cash=available_cash,
            days_left=days_left,
            wishlist_name=wishlist_name,
        )

        menu_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="open_menu")],
        ])
        await bot.send_message(chat_id=tg_id, text=text, reply_markup=menu_kb)
        logger.info(f"Вечерний отчёт отправлен {tg_id}")
        return True
    except Exception as e:
        logger.error(f"Не удалось отправить вечерний отчёт для {tg_id}: {e}")
        return False


async def send_auto_close_reports(bot: Bot):
    logger.info("Запуск авто-закрытия дня в 23:30...")

    async with async_session_maker() as session:
        result = await session.execute(select(User.telegram_id))
        user_ids = result.scalars().all()

    for tg_id in user_ids:
        if tg_id in _reported_today:
            continue
        await send_actual_report(tg_id, bot)
        await asyncio.sleep(0.05)

    logger.info("Авто-закрытие дня завершено.")
