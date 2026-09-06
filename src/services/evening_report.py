import asyncio
import logging
import random

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from ..bot.middleware import _last_keyboard
from ..core.config import settings
from ..db.database import async_session_maker
from ..db.models.models import User, UserSettings
from ..utils import phrases
from ..utils.helpers import get_msk_now, get_user_now
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
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
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
                user_settings = settings_result.scalar_one_or_none()
                if user_settings and not user_settings.notifications_enabled:
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
                _last_keyboard.pop(tg_id, None)
                try:
                    await bot.delete_message(chat_id=tg_id, message_id=container_id)
                except Exception:
                    pass

            recovery_extra = ""
            if settings.RECOVERY_ENABLED:
                try:
                    from sqlalchemy import func
                    from sqlalchemy import select as sa_select

                    from ..db.database import async_session_maker as _asm
                    from ..db.models.models import Expense as _Expense
                    from ..services.budget_service import get_active_budget as _get_budget
                    from ..services.recovery_service import (
                        get_active_recovery,
                        is_small_overspend,
                        recalculate_days,
                        update_recovery_days,
                    )

                    budget = await _get_budget(tg_id)
                    if budget:
                        active = await get_active_recovery(tg_id)
                        if active:
                            # spent today
                            async with _asm() as session:
                                today_start = get_user_now().replace(
                                    hour=0, minute=0, second=0, microsecond=0
                                )
                                result = await session.execute(
                                    sa_select(func.sum(_Expense.amount)).where(
                                        _Expense.telegram_id == tg_id,
                                        _Expense.is_deleted == False,
                                        _Expense.date >= today_start,
                                    )
                                )
                                spent_today = result.scalar() or 0
                                from ..services.monthly_report import get_period_dates

                                period_start, period_end = get_period_dates(budget)
                                next_day = period_end + __import__("datetime").timedelta(days=1)
                                result = await session.execute(
                                    sa_select(func.sum(_Expense.amount)).where(
                                        _Expense.telegram_id == tg_id,
                                        _Expense.is_deleted == False,
                                        _Expense.date >= period_start,
                                        _Expense.date < next_day,
                                    )
                                )
                                spent_period = result.scalar() or 0
                            if budget.free_money > 0:
                                money_for_life = budget.free_money
                            else:
                                money_for_life = (
                                    budget.total_income
                                    - budget.mandatory_payments
                                    - budget.black_day_fund
                                    - spent_period
                                )
                            days_left = budget.days_remaining
                            old_days = active.total_days
                            deficit = max(active.baseline * days_left - money_for_life, 0)
                            new_days = recalculate_days(deficit, active.baseline, active.target)
                            if new_days and new_days != old_days:
                                await update_recovery_days(tg_id, new_days)
                                cur_day = (get_user_now().date() - active.started_at.date()).days + 1
                                cur_day = max(cur_day, 1)
                                recovery_extra = (
                                    f"\n\n{phrases.RECOVERY_EVENING_HEADER.format(cur=cur_day, total=old_days)}\n"
                                    + phrases.RECOVERY_EVENING_SAVED.format(
                                        spent=int(spent_today),
                                        target=int(active.target),
                                        saved=int(max(active.target - spent_today, 0)),
                                    )
                                    + f"\n{phrases.RECOVERY_EVENING_SHORTENED.format(old=old_days, new=new_days, word='дней' if new_days % 10 != 1 else 'день')}"
                                )
                            else:
                                cur_day = (get_user_now().date() - active.started_at.date()).days + 1
                                cur_day = max(cur_day, 1)
                                total = new_days or old_days
                                if spent_today <= active.target:
                                    if spent_today == active.target:
                                        recovery_extra = (
                                            f"\n\n{phrases.RECOVERY_EVENING_HEADER.format(cur=cur_day, total=total)}\n"
                                            + phrases.RECOVERY_EVENING_EXACT.format(
                                                spent=int(spent_today), target=int(active.target)
                                            )
                                            + f"\n{phrases.RECOVERY_EVENING_GOOD}"
                                        )
                                    else:
                                        saved = int(active.target - spent_today)
                                        recovery_extra = (
                                            f"\n\n{phrases.RECOVERY_EVENING_HEADER.format(cur=cur_day, total=total)}\n"
                                            + phrases.RECOVERY_EVENING_SAVED.format(
                                                spent=int(spent_today),
                                                target=int(active.target),
                                                saved=saved,
                                            )
                                        )
                                        # forecast only if positive
                                        if saved > 0:
                                            sim_deficit = max(
                                                active.baseline * days_left - (money_for_life + saved), 0
                                            )
                                            sim_days = recalculate_days(
                                                sim_deficit, active.baseline, active.target
                                            )
                                            if sim_days and sim_days < total:
                                                diff = total - sim_days
                                                recovery_extra += "\n" + phrases.RECOVERY_EVENING_FORECAST.format(
                                                    n=diff, word="дней" if diff % 10 != 1 else "день"
                                                )
                                else:
                                    if is_small_overspend(spent_today, active.target):
                                        recovery_extra = (
                                            f"\n\n{phrases.RECOVERY_EVENING_HEADER.format(cur=cur_day, total=total)}\n"
                                            + phrases.RECOVERY_EVENING_EXACT.format(
                                                spent=int(spent_today), target=int(active.target)
                                            )
                                            + f"\n{phrases.RECOVERY_EVENING_SLIGHT}"
                                        )
                                    else:
                                        recovery_extra = (
                                            f"\n\n{phrases.RECOVERY_EVENING_HEADER.format(cur=cur_day, total=total)}\n"
                                            + phrases.RECOVERY_EVENING_EXACT.format(
                                                spent=int(spent_today), target=int(active.target)
                                            )
                                            + f"\n{phrases.RECOVERY_EVENING_HEAVY}"
                                        )
                except Exception as e:
                    logger.error(f"Recovery evening failed {tg_id}: {e}", exc_info=True)

            kb = None
            if not settings.EXPENSE_SIMPLE_CHECK:
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=phrases.BTN_BACK_MAIN, callback_data="report_back"
                            )
                        ],
                    ]
                )
            await bot.send_message(
                tg_id,
                random.choice(phrases.AUTO_CLOSE).format(total=f"{int(total):,}") + recovery_extra,
                reply_markup=kb,
            )

            await state.clear()
            logger.info(f"Авто-закрытие вечерней сессии {tg_id}")
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Ошибка авто-закрытия для {tg_id}: {e}")

    logger.info("Авто-закрытие дня завершено.")
