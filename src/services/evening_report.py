import random
import logging
import asyncio
from datetime import datetime

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import StorageKey, BaseStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select

from ..db.database import async_session_maker
from ..db.models.models import User, UserSettings
from ..utils.helpers import safe
from .expense_service import get_today_expenses_sum, get_today_daily_limit

logger = logging.getLogger(__name__)


class EveningState(StatesGroup):
    filling = State()


EVENING_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🏁 Показать отчет", callback_data="show_final_evening_report")],
])

INITIAL_TEXT = (
    "👁 День подошел к концу, время зафиксировать добычу.\n\n"
    "Если забыла внести какие-то расходы (аптеку, такси или тот самый кофе), "
    "просто напиши их сюда обычным сообщением. Я добавлю их к сегодняшнему дню.\n\n"
    "Если всё учтено — отсекаем лишнее и смотрим итог."
)


def _build_container_text(session_expenses: list[str]) -> str:
    if not session_expenses:
        return INITIAL_TEXT
    expenses_text = "\n".join(session_expenses)
    return (
        f"👁 Оп, поймал. Докидываю в общую кучу, вот что пока вспомнили:\n\n"
        f"{expenses_text}\n\n"
        f"Что-то еще выпало из кармана? Пиши, не стесняйся. Или сворачиваемся."
    )


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

        f"🔋 <b>Вечерний аудит:</b>\nСегодня мы шиканули на лишние <b>{int(overdraft)} ₽</b>. Это не катастрофа, но «{safe(wishlist_name)}» отодвинулась примерно на <b>{wishlist_delay} дн.</b> назад в будущее. 🗺 Убираю калькулятор, ложись спать, утро вечера мудренее.",

        f"📊 <b>Фиксирую дневной овердрафт:</b>\nМы вышли за край на <b>{int(overdraft)} ₽</b>. Если не сбавим обороты, последние <b>{min(5, days_left)} дн.</b> до зарплаты придётся провести в режиме супер-эконома. Закрывай банковские приложения, на сегодня финансовые игры окончены. Спокойной ночи! 🌙",
    ]
    return random.choice(evening_phrases)


async def send_evening_teaser(bot: Bot, storage: BaseStorage):
    logger.info("Запуск вечернего тизера в 22:00...")

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

            msg = await bot.send_message(tg_id, INITIAL_TEXT, reply_markup=EVENING_KB)

            storage_key = StorageKey(bot_id=bot.id, chat_id=tg_id, user_id=tg_id)
            state = FSMContext(storage=storage, key=storage_key)
            await state.set_state(EveningState.filling)
            await state.update_data(container_id=msg.message_id, session_expenses=[])

            logger.info(f"Вечерняя сессия открыта {tg_id}")
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Не удалось открыть вечернюю сессию для {tg_id}: {e}")

    logger.info("Рассылка вечерних сессий завершена.")


async def send_auto_close_reports(bot: Bot, storage: BaseStorage):
    logger.info("Запуск авто-закрытия дня в 23:30...")

    async with async_session_maker() as session:
        result = await session.execute(select(User.telegram_id))
        user_ids = result.scalars().all()

    for tg_id in user_ids:
        try:
            storage_key = StorageKey(bot_id=bot.id, chat_id=tg_id, user_id=tg_id)
            state = FSMContext(storage=storage, key=storage_key)
            current_state = await state.get_state()
            if current_state != EveningState.filling.state:
                continue

            data = await state.get_data()
            container_id = data.get("container_id")

            if container_id:
                try:
                    await bot.edit_message_reply_markup(
                        chat_id=tg_id, message_id=container_id, reply_markup=None
                    )
                except Exception:
                    pass

            total = await get_today_expenses_sum(tg_id)

            await bot.send_message(
                tg_id,
                f"🌙 <b>23:30 — Время вышло, подводим итоги автоматически.</b>\n\n"
                f"Твой фундамент на сегодня: <b>{int(total):,} ₽</b>.\n"
                f"Состояние сброшено.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="open_menu")],
                ]),
            )

            await state.clear()
            logger.info(f"Авто-закрытие вечерней сессии {tg_id}")
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Ошибка авто-закрытия для {tg_id}: {e}")

    logger.info("Авто-закрытие дня завершено.")
