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
from .expense_service import get_yesterday_expenses_sum

logger = logging.getLogger(__name__)


def _plural_days(n: int) -> str:
    n = abs(n) % 100
    n1 = n % 10
    if 11 <= n <= 14:
        return "дней"
    if n1 == 1:
        return "день"
    if 2 <= n1 <= 4:
        return "дня"
    return "дней"


def _build_recovery_morning_extra(tg_id: int) -> list[list[InlineKeyboardButton]] | None:
    if not settings.RECOVERY_ENABLED:
        return None
    return None


def _build_morning_keyboard(btn_type: str) -> InlineKeyboardMarkup | None:
    has_reply_kb = settings.EXPENSE_SIMPLE_CHECK
    base: list[list[InlineKeyboardButton]] = []
    if btn_type == "FRESH_START":
        base = [
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
                    user_settings = settings_result.scalar_one_or_none()
                    if user_settings and not user_settings.notifications_enabled:
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
                                tg_id,
                                offer,
                                reply_markup=get_rollover_keyboard(b.id),
                            )
                            if settings.RECOVERY_ENABLED:
                                try:
                                    from .recovery_service import (
                                        expire_active_recoveries_for_budget,
                                    )

                                    await expire_active_recoveries_for_budget(b.id)
                                except Exception:
                                    pass

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
                from .budget_service import get_daily_pred, get_money_for_life, get_period_spent

                spent_period = await get_period_spent(tg_id, budget)
                money_for_life = get_money_for_life(budget, spent_period)
                days_left = budget.days_remaining
                dl_base = budget.daily_limit
                dl_pred = get_daily_pred(money_for_life, days_left)
                pct_pred = dl_pred / max(dl_base, 1) * 100 if dl_base > 0 else 0

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
                    zone = "YELLOW_SIM_NONE"
                    btn_type = "REGULAR"
                else:
                    zone = "RED_DEAD"
                    btn_type = "FRESH_START"

                days_text = f"{days_left} {_plural_days(days_left)}"
                if zone == "END_EMPTY":
                    zone_text = random.choice(
                        [
                            phrases.ZONE_END_EMPTY_1.format(days_text=days_text),
                            phrases.ZONE_END_EMPTY_2.format(days_text=days_text),
                        ]
                    )
                elif zone == "END_OK":
                    zone_text = random.choice(
                        [
                            phrases.ZONE_END_OK_1.format(
                                days_text=days_text, money=int(money_for_life)
                            ),
                            phrases.ZONE_END_OK_2.format(
                                days_text=days_text, money=int(money_for_life)
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
                elif zone == "YELLOW_SIM_NONE":
                    zone_text = random.choice(
                        [
                            phrases.MORNING_YELLOW_SIM_NONE_1.format(limit=int(dl_pred)),
                            phrases.MORNING_YELLOW_SIM_NONE_2.format(limit=int(dl_pred)),
                            phrases.MORNING_YELLOW_BUDGET_NERVOUS.format(limit=int(dl_pred)),
                        ]
                    )
                else:
                    zone_text = random.choice(
                        [
                            phrases.MORNING_RED_DEAD_1,
                            phrases.MORNING_RED_DEAD_2,
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
                if settings.RECOVERY_ENABLED:
                    try:
                        from ..utils.helpers import get_user_now
                        from .budget_service import resolve_frozen_baseline
                        from .recovery_service import (
                            calculate_recovery_options,
                            check_success,
                            complete_recovery,
                            get_active_recovery,
                            get_offer_state,
                            should_repeat_offer,
                        )

                        active = await get_active_recovery(tg_id)
                        if active:
                            if check_success(dl_pred, active.baseline):
                                await complete_recovery(tg_id, "success")
                                full_text += "\n\n" + phrases.RECOVERY_SUCCESS.format(
                                    baseline=int(active.baseline)
                                )
                            else:
                                cur_day = (
                                    get_user_now().date() - active.started_at.date()
                                ).days + 1
                                cur_day = max(cur_day, 1)
                                tail = max(days_left - active.total_days, 0)
                                full_text += "\n\n" + phrases.RECOVERY_DAILY_ACTIVE.format(
                                    cur=cur_day,
                                    total=active.total_days,
                                    target=int(active.target),
                                    days=active.total_days,
                                    days_word="дней" if active.total_days % 10 != 1 else "день",
                                    baseline=int(active.baseline),
                                    tail=tail,
                                    tail_word="дней" if tail % 10 != 1 else "день",
                                )
                                if kb:
                                    rows = list(kb.inline_keyboard)
                                    rows.append(
                                        [
                                            InlineKeyboardButton(
                                                text=phrases.BTN_RECOVERY_STOP,
                                                callback_data="recovery:stop",
                                            )
                                        ]
                                    )
                                    kb = InlineKeyboardMarkup(inline_keyboard=rows)
                                else:
                                    kb = InlineKeyboardMarkup(
                                        inline_keyboard=[
                                            [
                                                InlineKeyboardButton(
                                                    text=phrases.BTN_RECOVERY_STOP,
                                                    callback_data="recovery:stop",
                                                )
                                            ]
                                        ]
                                    )
                        else:
                            b_val = await resolve_frozen_baseline(budget)
                            opts = calculate_recovery_options(b_val, money_for_life, days_left)
                            if opts:
                                offer_state = await get_offer_state(tg_id)
                                should_show = True
                                if (
                                    offer_state
                                    and offer_state.dismissed
                                    and offer_state.last_offer_at
                                ):
                                    days_since = (
                                        get_user_now().date() - offer_state.last_offer_at.date()
                                    ).days
                                    cur_deficit = max(b_val * days_left - money_for_life, 0)
                                    if not should_repeat_offer(
                                        offer_state.last_offer_deficit,
                                        cur_deficit,
                                        b_val,
                                        days_since,
                                    ):
                                        should_show = False
                                if should_show:
                                    full_text += "\n\n" + phrases.RECOVERY_DAILY_OFFER.format(
                                        dl_pred=int(dl_pred)
                                    )
                                    if kb:
                                        rows = list(kb.inline_keyboard)
                                        rows.append(
                                            [
                                                InlineKeyboardButton(
                                                    text=phrases.BTN_RECOVERY_PLAN,
                                                    callback_data="recovery:show_options",
                                                )
                                            ]
                                        )
                                        kb = InlineKeyboardMarkup(inline_keyboard=rows)
                                    else:
                                        kb = InlineKeyboardMarkup(
                                            inline_keyboard=[
                                                [
                                                    InlineKeyboardButton(
                                                        text=phrases.BTN_RECOVERY_PLAN,
                                                        callback_data="recovery:show_options",
                                                    )
                                                ]
                                            ]
                                        )
                    except Exception as e:
                        logger.error(f"Recovery morning failed {tg_id}: {e}", exc_info=True)

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
