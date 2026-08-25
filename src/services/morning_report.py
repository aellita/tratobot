import asyncio
import logging
import random
from datetime import timedelta

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from ..core.config import settings
from ..db.database import async_session_maker
from ..db.models.models import DailyReportsLog, User, UserSettings
from ..utils import phrases
from ..utils.helpers import get_msk_now
from .expense_service import get_current_period_expenses_sum, get_yesterday_expenses_sum

logger = logging.getLogger(__name__)


def _build_morning_keyboard(btn_type: str) -> InlineKeyboardMarkup | None:
    has_reply_kb = settings.EXPENSE_SIMPLE_CHECK
    base: list[list[InlineKeyboardButton]] = []
    if btn_type == "FRESH_START":
        base = [
            [InlineKeyboardButton(text=phrases.BTN_RECALC_LIMIT, callback_data="recalc_limit")],
        ]
    elif btn_type == "FROM_YELLOW_TO_GREEN":
        base = [
            [InlineKeyboardButton(text=phrases.BTN_USE_SAVINGS_COMFORT, callback_data="use_savings")],
            [InlineKeyboardButton(text=phrases.BTN_ECONOMIZE, callback_data="menu_back")],
        ]
    elif btn_type == "FROM_YELLOW_TO_BLUE":
        base = [
            [InlineKeyboardButton(text=phrases.BTN_RAISE_LIMIT_SAVINGS, callback_data="use_savings")],
            [InlineKeyboardButton(text=phrases.BTN_ECONOMIZE, callback_data="menu_back")],
        ]
    elif btn_type == "FROM_RED_TO_GREEN":
        base = [
            [InlineKeyboardButton(text=phrases.BTN_RESTORE_GREEN_SAVINGS, callback_data="use_savings")],
            [InlineKeyboardButton(text=phrases.BTN_RECALC_LIMIT, callback_data="recalc_limit")],
        ]
    elif btn_type == "FROM_RED_TO_BLUE":
        base = [
            [InlineKeyboardButton(text=phrases.BTN_EXIT_CRISIS_GREEN, callback_data="use_savings")],
            [InlineKeyboardButton(text=phrases.BTN_RECALC_LIMIT, callback_data="recalc_limit")],
        ]
    elif btn_type == "FROM_RED_TO_YELLOW":
        base = [
            [InlineKeyboardButton(text=phrases.BTN_SAVE_BUDGET_SAVINGS, callback_data="use_savings")],
            [InlineKeyboardButton(text=phrases.BTN_RECALC_LIMIT, callback_data="recalc_limit")],
        ]
    if not has_reply_kb:
        base.append([InlineKeyboardButton(text=phrases.BTN_BACK_MAIN, callback_data="report_back")])
    return InlineKeyboardMarkup(inline_keyboard=base) if base else None


async def _has_morning_report_today(tg_id: int, session) -> bool:
    today = get_msk_now().date()
    result = await session.execute(
        select(DailyReportsLog).where(
            DailyReportsLog.telegram_id == tg_id,
            DailyReportsLog.report_type == "morning",
            DailyReportsLog.sent_date == today,
        )
    )
    return result.scalar_one_or_none() is not None


async def _log_morning_report(tg_id: int, session):
    today = get_msk_now().date()
    session.add(DailyReportsLog(telegram_id=tg_id, report_type="morning", sent_date=today))
    await session.commit()


async def send_morning_reports(bot: Bot):
    logger.info("Запуск утренней рассылки в 08:00...")
    try:
        async with async_session_maker() as session:
            result = await session.execute(select(User.telegram_id))
            user_ids = result.scalars().all()

        for tg_id in user_ids:
            try:
                async with async_session_maker() as session:
                    if await _has_morning_report_today(tg_id, session):
                        continue

                    settings_result = await session.execute(
                        select(UserSettings).where(UserSettings.telegram_id == tg_id)
                    )
                    settings = settings_result.scalar_one_or_none()
                    if settings and not settings.notifications_enabled:
                        continue

                from ..bot.keyboards import get_rollover_keyboard
                from ..bot.rich_api import send_rich_message
                from ..db.models.models import Budget as BudgetModel
                from ..utils import phrases
                from .monthly_report import (
                    build_summary_data,
                    format_summary_text,
                    get_average_expenses,
                    get_period_dates,
                )

                today = get_msk_now().date()
                sent_summary = False
                async with async_session_maker() as session:
                    result = await session.execute(
                        select(BudgetModel).where(BudgetModel.telegram_id == tg_id)
                    )
                    for b in result.scalars().all():
                        _, pe = get_period_dates(b)
                        if today == pe.date() + timedelta(days=1):
                            data = await build_summary_data(tg_id, b)
                            msg = format_summary_text(data)
                            await send_rich_message(bot, tg_id, msg)

                            avg = await get_average_expenses(tg_id)
                            offer = phrases.ROLLOVER_OFFER.format(
                                old_date=b.period_start_day or 1,
                                avg=int(avg) if avg > 0 else 0,
                                old_income=int(b.total_income),
                            )
                            await bot.send_message(
                                tg_id, offer,
                                reply_markup=get_rollover_keyboard(b.id),
                            )

                            async with async_session_maker() as log_session:
                                await _log_morning_report(tg_id, log_session)
                            logger.info(f"Ежемесячный отчёт и rollover отправлены {tg_id}")
                            sent_summary = True
                            break

                if sent_summary:
                    continue

                from .budget_service import get_active_budget

                budget = await get_active_budget(tg_id)

                if not budget or budget.daily_limit <= 0:
                    continue

                period_start, period_end = get_period_dates(budget)

                yesterday_spent = await get_yesterday_expenses_sum(tg_id)
                spent_period = await get_current_period_expenses_sum(tg_id)

                days_left = budget.days_remaining
                dl_base = budget.daily_limit
                savings = budget.black_day_fund

                if budget.free_money > 0:
                    money_for_life = budget.free_money - spent_period
                else:
                    money_for_life = (
                        budget.total_income
                        - budget.mandatory_payments
                        - budget.black_day_fund
                        - spent_period
                    )

                dl_pred = max(money_for_life / max(days_left, 1), 0) if money_for_life > 0 else 0
                dl_simulated = max((money_for_life + savings) / max(days_left, 1), 0)
                pct_pred = dl_pred / max(dl_base, 1) * 100 if dl_base > 0 else 0
                pct_sim = dl_simulated / max(dl_base, 1) * 100 if dl_base > 0 else 0

                end_of_period = days_left <= 3

                overdraft = max(yesterday_spent - dl_pred, 0)
                if yesterday_spent <= dl_pred:
                    yesterday_line = phrases.YESTERDAY_OK.format(
                        spent=int(yesterday_spent), limit=int(dl_pred)
                    )
                else:
                    yesterday_line = phrases.YESTERDAY_OVER.format(
                        spent=int(yesterday_spent), limit=int(dl_pred), over=int(overdraft)
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
                    zone_text = random.choice(
                        [
                            phrases.ZONE_END_EMPTY_1.format(days_left=days_left),
                            phrases.ZONE_END_EMPTY_2.format(days_left=days_left),
                        ]
                    )
                elif zone == "END_OK":
                    zone_text = random.choice(
                        [
                            phrases.ZONE_END_OK_1.format(
                                days_left=days_left, money=int(money_for_life)
                            ),
                            phrases.ZONE_END_OK_2.format(
                                days_left=days_left, money=int(money_for_life)
                            ),
                        ]
                    )
                elif zone == "GREEN":
                    zone_text = random.choice(
                        [
                            phrases.ZONE_GREEN_1.format(limit=int(dl_pred)),
                            phrases.ZONE_GREEN_2.format(limit=int(dl_pred)),
                        ]
                    )
                elif zone == "YELLOW_LIGHT":
                    zone_text = random.choice(
                        [
                            phrases.ZONE_YELLOW_LIGHT_1.format(limit=int(dl_pred)),
                            phrases.ZONE_YELLOW_LIGHT_2.format(limit=int(dl_pred)),
                        ]
                    )
                elif zone == "YELLOW_SIM_GREEN":
                    # TODO: extract to phrases.py
                    zone_text = random.choice(
                        [
                            f"🟨 Режим турбо-экономии! Прогноз: {int(dl_pred):,} ₽/день.\n"
                            f"💡 Кубышка ({int(savings):,} ₽) вернёт нас в зелёную зону — лимит будет {int(dl_simulated):,} ₽/день!",
                            f"🟨 Затягиваем пояса — прогноз {int(dl_pred):,} ₽/день.\n"
                            f"💡 Вскрываем Кубышку? Это подбросит лимит до {int(dl_simulated):,} ₽/день!",
                        ]
                    )
                elif zone == "YELLOW_SIM_BLUE":
                    # TODO: extract to phrases.py
                    zone_text = random.choice(
                        [
                            f"🟨 Режим турбо-экономии! Прогноз: {int(dl_pred):,} ₽/день.\n"
                            f"💡 Кубышка поднимет лимит до <b>{int(dl_simulated):,} ₽</b>/день.",
                            f"🟨 Бюджет трещит по швам, прогноз {int(dl_pred):,} ₽/день.\n"
                            f"💡 Кубышка готова помочь — поднимем планку до {int(dl_simulated):,} ₽/день!",
                        ]
                    )
                elif zone == "YELLOW_SIM_NONE":
                    # TODO: extract to phrases.py
                    zone_text = random.choice(
                        [
                            f"🟨 Режим турбо-экономии. Прогноз: {int(dl_pred):,} ₽/день. Держимся!",
                            f"🟨 Включаю режим супер-экономии. Прогноз {int(dl_pred):,} ₽/день.",
                        ]
                    )
                elif zone == "RED_SIM_GREEN":
                    # TODO: extract to phrases.py
                    zone_text = random.choice(
                        [
                            f"🔴 Мы на дне! Прогноз: {int(dl_pred):,} ₽/день.\n"
                            f"💡 Кубышка ({int(savings):,} ₽) моментом вытащит нас! Лимит взлетит до <b>{int(dl_simulated):,} ₽</b>/день!",
                            f"🔴 Критическая ситуация: {int(dl_pred):,} ₽/день.\n"
                            f"💡 Секретное оружие — Кубышка! Лимит станет {int(dl_simulated):,} ₽/день!",
                        ]
                    )
                elif zone == "RED_SIM_BLUE":
                    # TODO: extract to phrases.py
                    zone_text = random.choice(
                        [
                            f"🔴 Глубокое пике. Прогноз: {int(dl_pred):,} ₽/день.\n"
                            f"💡 Кубышка вытащит нас в стабильную зону: {int(dl_simulated):,} ₽/день!",
                            f"🔴 Бюджет на минимуме — {int(dl_pred):,} ₽/день.\n"
                            f"💡 Время вскрывать резервы! Кубышка поднимет лимит до {int(dl_simulated):,} ₽/день!",
                        ]
                    )
                elif zone == "RED_SIM_YELLOW":
                    # TODO: extract to phrases.py
                    zone_text = random.choice(
                        [
                            f"🔴 Мы на дне. Прогноз: {int(dl_pred):,} ₽/день.\n"
                            f"💡 Кубышка ({int(savings):,} ₽) подрастит лимит до {int(dl_simulated):,} ₽/день.",
                            f"🔴 Денег почти не осталось — {int(dl_pred):,} ₽/день.\n"
                            f"💡 Кубышка смягчит падение: лимит будет {int(dl_simulated):,} ₽/день.",
                        ]
                    )
                else:
                    # TODO: extract to phrases.py
                    zone_text = random.choice(
                        [
                            "🔴 Мы пробили дно. Денег нет. 🚀 Нужен пересчёт лимита.",
                            "🔴 Катастрофа! Бюджет исчерпан. Пора пересчитать лимит.",
                        ]
                    )

                full_text = (
                    phrases.MORNING_GREETING
                    + phrases.MORNING_TODAY_PLAN.format(limit=int(dl_pred))
                    + "\n\n"
                    + yesterday_line
                    + "\n\n"
                    + zone_text
                )

                kb = _build_morning_keyboard(btn_type)
                await bot.send_message(tg_id, full_text, reply_markup=kb)

                async with async_session_maker() as session:
                    await _log_morning_report(tg_id, session)

                logger.info(f"Утренний отчёт отправлен {tg_id} (зона {zone})")

                await asyncio.sleep(0.05)
            except Exception as e:
                logger.error(f"Ошибка утреннего отчёта {tg_id}: {e}")

        logger.info("Утренняя рассылка завершена.")
    except Exception as e:
        logger.error(f"Критическая ошибка утренней рассылки: {e}", exc_info=True)
