import asyncio
import logging
import random

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from ..db.database import async_session_maker
from ..db.models.models import User, UserSettings
from ..utils import phrases
from ..utils.helpers import get_msk_now
from .expense_service import get_today_expenses_grouped, get_today_expenses_sum

logger = logging.getLogger(__name__)


class EveningState(StatesGroup):
    filling = State()


EVENING_KB = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text=phrases.BTN_SHOW_REPORT, callback_data="show_final_evening_report"
            )
        ],
    ]
)

INITIAL_TEXT = phrases.EVENING_INITIAL


def _build_container_text(session_expenses: list[str]) -> str:
    if not session_expenses:
        return INITIAL_TEXT
    expenses_text = "\n".join(session_expenses)
    return phrases.EVENING_CONTAINER.format(expenses=expenses_text)


def get_evening_message(limit: float, spent: float, available_cash: float, days_left: int) -> str:
    if spent <= limit:
        saved = limit - spent
        if int(spent) == 0:
            green_phrases = [
                phrases.EVENING_ZERO_1.format(limit=int(limit)),
                phrases.EVENING_ZERO_2,
                phrases.EVENING_ZERO_3,
            ]
        else:
            green_phrases = [
                phrases.EVENING_GREEN_1.format(
                    limit=int(limit), spent=int(spent), saved=int(saved)
                ),
                phrases.EVENING_GREEN_2.format(limit=int(limit), spent=int(spent)),
                phrases.EVENING_GREEN_3.format(limit=int(limit), spent=int(spent)),
                phrases.EVENING_GREEN_4.format(spent=int(spent), saved=int(saved)),
            ]
        return random.choice(green_phrases)

    overdraft = spent - limit
    days_to_grease = int(available_cash / overdraft) if overdraft > 0 else days_left
    days_to_grease = max(1, min(days_to_grease, days_left))

    evening_phrases = [
        phrases.EVENING_OVER_1.format(over=int(overdraft), days=days_to_grease),
        phrases.EVENING_OVER_2.format(over=int(overdraft), days_left=days_left),
        phrases.EVENING_OVER_3.format(over=int(overdraft), days=min(5, days_left)),
    ]
    return random.choice(evening_phrases)


_MONTH_NAMES_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}


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

            storage_key = StorageKey(bot_id=bot.id, chat_id=tg_id, user_id=tg_id)
            state = FSMContext(storage=storage, key=storage_key)
            current_state = await state.get_state()
            if current_state is not None:
                logger.info(f"Пользователь {tg_id} занят в {current_state}, тизер пропущен")
                continue

            today = get_msk_now()
            date_str = f"{today.day} {_MONTH_NAMES_RU[today.month]}"
            expense_lines = await get_today_expenses_grouped(tg_id)

            if expense_lines:
                quote_lines = [f"> Сегодня, {date_str}:"]
                quote_lines.extend(f"> {line}" for line in expense_lines)
                blockquote = "\n".join(quote_lines)
                teaser_text = f"{INITIAL_TEXT}\n\n{blockquote}"
            else:
                teaser_text = INITIAL_TEXT

            msg = await bot.send_message(tg_id, teaser_text, reply_markup=EVENING_KB)
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

            if current_state is None:
                continue

            is_evening_state = current_state == EveningState.filling.state

            if is_evening_state:
                data = await state.get_data()
                container_id = data.get("container_id")
                if container_id:
                    try:
                        await bot.edit_message_reply_markup(
                            chat_id=tg_id, message_id=container_id, reply_markup=None
                        )
                    except Exception:
                        pass
            else:
                await state.clear()
                await bot.send_message(
                    tg_id,
                    phrases.EVENING_TIMEOUT,
                )

            total = await get_today_expenses_sum(tg_id)

            if is_evening_state:
                try:
                    await bot.delete_message(chat_id=tg_id, message_id=container_id)
                except Exception:
                    pass

            await bot.send_message(
                tg_id,
                phrases.AUTO_CLOSE.format(total=f"{int(total):,}"),
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=phrases.BTN_BACK_MAIN, callback_data="report_back"
                            )
                        ],
                    ]
                ),
            )

            await state.clear()
            logger.info(f"Авто-закрытие вечерней сессии {tg_id}")
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Ошибка авто-закрытия для {tg_id}: {e}")

    logger.info("Авто-закрытие дня завершено.")
