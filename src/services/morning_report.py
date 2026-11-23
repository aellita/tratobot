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
from .budget_service import get_plan_today
from .expense_service import get_today_expenses_sum, get_yesterday_expenses_sum
from .status_zones import (
    PRESSURE_GREEN_MIN,
    PRESSURE_LIGHT_MIN,
    PRESSURE_NONE_MIN,
    is_end_of_period,
    limit_pressure_pct,
)

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


def _yesterday_plan(
    money_for_life_raw: float,
    yesterday_spent: float,
    spent_today: float,
    days_left: int,
) -> float:
    """План, который действовал вчера: остаток до вчерашних трат / дни на вчера.

    ``money_for_life_raw`` — остаток **сейчас**, уже после сегодняшних и
    вчерашних трат. Чтобы получить остаток на начало вчера, возвращаем оба
    дня, а дней на вчера было ``days_left + 1``.

    ``spent_today_at_recalc`` сюда передавать нельзя: снапшот уже вычтен
    из ``money_for_life_raw``.
    """
    return get_plan_today(money_for_life_raw, yesterday_spent + spent_today, days_left + 1)


def _yesterday_line(yesterday_spent: float, plan_yesterday: float) -> tuple[str, bool]:
    """Строка «Вчера» и признак «уложился».

    Сравниваем ровно те числа, которые показываем, чтобы не появлялось
    «потратил 1000 из 1000 — перебор 0 ₽» из-за копеек.
    """
    spent_int = int(yesterday_spent)
    limit_int = int(plan_yesterday)
    if spent_int <= limit_int:
        return phrases.YESTERDAY_OK.format(spent=spent_int, limit=limit_int), True
    return (
        phrases.YESTERDAY_OVER.format(spent=spent_int, limit=limit_int, over=spent_int - limit_int),
        False,
    )


def _select_morning_zone(
    *,
    end_of_period: bool,
    money_for_life: float,
    free_today: float,
    overrun_today: float,
    plan_today: float,
    base_daily_limit: float,
    yesterday_ok: bool,
) -> str:
    if end_of_period:
        if money_for_life <= 0:
            return "END_EMPTY"
        if overrun_today > 0:
            return "END_OVER"
        # B23: новая логика для последних 3 дней
        # Используем округлённое значение (как в отображении) для консистентности 70%
        plan_today_rounded = int(round(plan_today))
        plan_ratio_ok = base_daily_limit > 0 and plan_today_rounded >= 0.7 * base_daily_limit - 1e-9
        if yesterday_ok and plan_ratio_ok:
            return "END_OK"
        if not yesterday_ok:
            return "END_YESTERDAY_OVERRUN"
        return "END_PLAN_SAGGED"
    if overrun_today > 0:
        return "OVER"
    if free_today <= 0:
        return "YELLOW_SIM_NONE"
    pct = limit_pressure_pct(plan_today, base_daily_limit)
    if pct >= PRESSURE_GREEN_MIN:
        # вчера был перебор — хвалить «ты машина» нельзя
        return "OVER_YESTERDAY" if not yesterday_ok else "GREEN"
    if pct >= PRESSURE_LIGHT_MIN:
        return "YELLOW_LIGHT_OK" if yesterday_ok else "YELLOW_LIGHT"
    if pct >= PRESSURE_NONE_MIN:
        return "YELLOW_SIM_NONE"
    return "RED_DEAD"


def _end_ok_text(days_left: int, money_for_life: float) -> str:
    """Финишный текст: один из трёх вариантов, сумма — где она уместна."""
    days_word = _plural_days(days_left)
    return random.choice(
        [
            phrases.END_OK.format(days=days_left, days_word=days_word),
            phrases.END_OK_1.format(days=days_left, days_word=days_word, money=money_for_life),
            phrases.END_OK_2.format(days=days_left, days_word=days_word, money=money_for_life),
        ]
    )


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


async def _log_morning_report(tg_id: int) -> None:
    async with async_session_maker() as session:
        today = get_msk_now().date()
        session.add(DailyReportsLog(telegram_id=tg_id, report_type="morning", sent_date=today))
        await session.commit()


async def send_morning_reports(bot: Bot):
    logger.info("Запуск утренней рассылки...")
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

                from ..bot.chart_delivery import send_monthly_chart
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
                budget_id_to_expire = None
                async with async_session_maker() as session:
                    result = await session.execute(
                        select(BudgetModel).where(BudgetModel.telegram_id == tg_id)
                    )
                    budgets = list(result.scalars().all())

                for b in budgets:
                    _, pe = get_period_dates(b)
                    if today != pe.date() + timedelta(days=1):
                        continue

                    data = await build_summary_data(tg_id, b)
                    msg = format_summary_text(data)
                    await send_rich_message(bot, tg_id, msg)

                    # Send chart (PNG primary, widget behind flag)
                    try:
                        await send_monthly_chart(bot, tg_id, tg_id, b, force_new=True)
                    except Exception as e:
                        logger.warning("Rollover chart send failed for %s: %s", tg_id, e)

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
                    budget_id_to_expire = b.id
                    logger.info(f"Ежемесячный отчёт и rollover отправлены {tg_id}")
                    sent_summary = True
                    break

                if sent_summary:
                    if settings.RECOVERY_ENABLED and budget_id_to_expire is not None:
                        try:
                            from .recovery_service import (
                                expire_active_recoveries_for_budget,
                            )

                            await expire_active_recoveries_for_budget(budget_id_to_expire)
                        except Exception:
                            pass
                    await _log_morning_report(tg_id)
                    await asyncio.sleep(0.05)
                    continue

                from .budget_service import get_active_budget

                budget = await get_active_budget(tg_id)

                if not budget:
                    continue

                from .daily_limits import refresh_daily_limit

                await refresh_daily_limit(tg_id)

                yesterday_spent = await get_yesterday_expenses_sum(tg_id)
                from .budget_service import (
                    get_base_daily_limit,
                    get_free_today,
                    get_money_for_life,
                    get_money_for_life_raw,
                    get_overrun_today,
                    get_period_spent,
                    get_plan_today,
                    get_spent_today_at_recalc,
                )

                spent_period = await get_period_spent(tg_id, budget)
                spent_today = await get_today_expenses_sum(tg_id)
                money_for_life_raw = get_money_for_life_raw(budget, spent_period)
                money_for_life = get_money_for_life(budget, spent_period)
                days_left = budget.days_remaining
                dl_base = await get_base_daily_limit(budget)
                spent_today_at_recalc = get_spent_today_at_recalc(budget)
                dl_pred = get_plan_today(
                    money_for_life_raw, spent_today, days_left, spent_today_at_recalc
                )
                free_today = get_free_today(dl_pred, spent_today)
                overrun_today = get_overrun_today(dl_pred, spent_today)

                end_of_period = is_end_of_period(days_left)
                plan_yesterday = _yesterday_plan(
                    money_for_life_raw, yesterday_spent, spent_today, days_left
                )
                yesterday_line, yesterday_ok = _yesterday_line(yesterday_spent, plan_yesterday)

                zone = _select_morning_zone(
                    end_of_period=end_of_period,
                    money_for_life=money_for_life,
                    free_today=free_today,
                    overrun_today=overrun_today,
                    plan_today=dl_pred,
                    base_daily_limit=dl_base,
                    yesterday_ok=yesterday_ok,
                )
                btn_type = "FRESH_START" if zone in {"END_EMPTY", "RED_DEAD"} else "REGULAR"

                days_text = f"{days_left} {_plural_days(days_left)}"
                plan_today_int = int(round(dl_pred))
                if zone == "END_EMPTY":
                    zone_text = random.choice(
                        [
                            phrases.ZONE_END_EMPTY_1.format(days_text=days_text),
                            phrases.ZONE_END_EMPTY_2.format(days_text=days_text),
                        ]
                    )
                elif zone == "END_OVER":
                    zone_text = random.choice(
                        [
                            phrases.ZONE_END_OVER_1.format(days_text=days_text),
                            phrases.ZONE_END_OVER_2.format(days_text=days_text),
                        ]
                    )
                elif zone == "END_OK":
                    zone_text = _end_ok_text(days_left, money_for_life)
                elif zone == "END_YESTERDAY_OVERRUN":
                    overrun_yesterday = int(round(max(yesterday_spent - plan_yesterday, 0)))
                    zone_text = phrases.END_YESTERDAY_OVERRUN.format(
                        overrun=overrun_yesterday,
                        days=days_left,
                        days_word=_plural_days(days_left),
                        plan=plan_today_int,
                    )
                elif zone == "END_PLAN_SAGGED":
                    zone_text = phrases.END_PLAN_SAGGED.format(
                        plan=plan_today_int,
                        days=days_left,
                        days_word=_plural_days(days_left),
                    )
                elif zone == "OVER":
                    zone_text = random.choice(
                        [
                            phrases.MORNING_OVER_1,
                            phrases.MORNING_OVER_2,
                        ]
                    )
                elif zone == "GREEN":
                    zone_text = random.choice(
                        [
                            phrases.ZONE_GREEN_1.format(limit=int(dl_pred)),
                            phrases.ZONE_GREEN_2.format(limit=int(dl_pred)),
                        ]
                    )
                elif zone == "OVER_YESTERDAY":
                    zone_text = phrases.MORNING_YESTERDAY_OVER_ZONE
                elif zone == "YELLOW_LIGHT":
                    zone_text = random.choice(
                        [
                            phrases.ZONE_YELLOW_LIGHT_1.format(limit=int(dl_pred)),
                            phrases.ZONE_YELLOW_LIGHT_2.format(limit=int(dl_pred)),
                        ]
                    )
                elif zone == "YELLOW_LIGHT_OK":
                    zone_text = phrases.ZONE_YELLOW_LIGHT_OK
                elif zone == "YELLOW_SIM_NONE":
                    options = [
                        phrases.MORNING_YELLOW_SIM_NONE_1.format(limit=int(dl_pred)),
                        phrases.MORNING_YELLOW_SIM_NONE_2.format(limit=int(dl_pred)),
                    ]
                    if dl_pred < dl_base:
                        options.append(
                            phrases.MORNING_YELLOW_BUDGET_NERVOUS.format(limit=int(dl_pred))
                        )
                    zone_text = random.choice(options)
                else:
                    zone_text = random.choice(
                        [
                            phrases.MORNING_RED_DEAD_1.format(limit=int(dl_pred)),
                            phrases.MORNING_RED_DEAD_2.format(limit=int(dl_pred)),
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
                            is_early_completion,
                            should_repeat_offer,
                        )

                        active = await get_active_recovery(tg_id)
                        if active:
                            if check_success(dl_pred, active.baseline):
                                if is_early_completion(active):
                                    await complete_recovery(tg_id, "early_success")
                                    full_text += "\n\n" + phrases.RECOVERY_SUCCESS_EARLY.format(
                                        baseline=int(active.baseline)
                                    )
                                else:
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

                await _log_morning_report(tg_id)

                logger.info(f"Утренний отчёт отправлен {tg_id} (зона {zone})")

                await asyncio.sleep(0.05)
            except Exception as e:
                logger.error(f"Ошибка утреннего отчёта {tg_id}: {e}")

        logger.info("Утренняя рассылка завершена.")
    except Exception as e:
        logger.error(f"Критическая ошибка утренней рассылки: {e}", exc_info=True)
