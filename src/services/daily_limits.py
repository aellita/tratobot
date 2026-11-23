"""Per-day limit snapshots (G2).

Stores the effective daily limit the user actually lived by: ``plan_today``
or an active Recovery target. Last write for a given day wins; past days are
never rewritten by later reconciliations.
"""

import logging
from datetime import date

from sqlalchemy import select

from ..db.database import async_session_maker
from ..db.models.models import Budget, DailyLimit
from ..utils.helpers import get_msk_now

logger = logging.getLogger(__name__)

SOURCE_PLAN = "plan"
SOURCE_RECOVERY = "recovery"


async def upsert_daily_limit(
    telegram_id: int,
    plan_date: date,
    limit: float,
    source: str = SOURCE_PLAN,
) -> None:
    """Write the effective limit for ``plan_date``. Last write wins."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(DailyLimit).where(
                DailyLimit.telegram_id == telegram_id,
                DailyLimit.plan_date == plan_date,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            session.add(
                DailyLimit(
                    telegram_id=telegram_id,
                    plan_date=plan_date,
                    limit=float(limit),
                    source=source,
                )
            )
        else:
            row.limit = float(limit)
            row.source = source
        await session.commit()


async def get_daily_limits(
    telegram_id: int,
    start: date,
    end: date,
) -> dict[date, float]:
    """Return ``{date: limit}`` for ``[start, end]`` inclusive."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(DailyLimit.plan_date, DailyLimit.limit)
            .where(DailyLimit.telegram_id == telegram_id)
            .where(DailyLimit.plan_date >= start)
            .where(DailyLimit.plan_date <= end)
        )
        return {plan_date: float(limit) for plan_date, limit in result.all()}


async def get_effective_daily_limit(
    telegram_id: int,
    budget: Budget | None = None,
) -> tuple[float, str] | None:
    """Return ``(limit, source)`` for today, or ``None`` if there is none.

    Active Recovery wins over the regular plan. Days outside the active
    period, periods already over and zero-base periods are skipped so the
    snapshot never stores a meaningless value.
    """
    from .budget_service import (
        get_active_budget,
        get_base_daily_limit,
        get_money_for_life_raw,
        get_period_spent,
        get_plan_today,
        get_spent_today_at_recalc,
    )
    from .expense_service import get_today_expenses_sum
    from .monthly_report import get_period_dates
    from .recovery_service import get_active_recovery

    if budget is None:
        budget = await get_active_budget(telegram_id)
    if budget is None:
        return None

    today = get_msk_now()
    period_start, period_end = get_period_dates(budget)
    if not period_start.date() <= today.date() <= period_end.date():
        return None
    if budget.days_remaining <= 0:
        return None
    if await get_base_daily_limit(budget) <= 0:
        return None

    recovery = await get_active_recovery(telegram_id)
    if recovery is not None and recovery.budget_id == budget.id:
        return max(float(recovery.target), 0.0), SOURCE_RECOVERY

    spent_period = await get_period_spent(telegram_id, budget)
    spent_today = await get_today_expenses_sum(telegram_id)
    plan_today = get_plan_today(
        get_money_for_life_raw(budget, spent_period),
        spent_today,
        budget.days_remaining,
        get_spent_today_at_recalc(budget),
    )
    return max(float(plan_today), 0.0), SOURCE_PLAN


async def refresh_daily_limit(telegram_id: int, budget: Budget | None = None) -> None:
    """Snapshot today's effective limit. Never raises into the caller."""
    try:
        effective = await get_effective_daily_limit(telegram_id, budget)
        if effective is None:
            return
        limit, source = effective
        await upsert_daily_limit(telegram_id, get_msk_now().date(), limit, source)
    except Exception:
        logger.warning("Failed to refresh daily limit for %s", telegram_id, exc_info=True)


async def refresh_all_daily_limits() -> int:
    """Snapshot today's limit for every user with a budget. Returns users seen."""
    async with async_session_maker() as session:
        result = await session.execute(select(Budget.telegram_id).distinct())
        telegram_ids = list(result.scalars().all())

    for telegram_id in telegram_ids:
        await refresh_daily_limit(telegram_id)
    return len(telegram_ids)
