"""Per-day limit snapshots (G2).

Stores the effective daily limit the user actually lived by: ``plan_today``
or an active Recovery target. Last write for a given day wins; past days are
never rewritten by later reconciliations.
"""

import logging
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from ..db.database import async_session_maker
from ..db.models.models import Budget, DailyLimit
from ..utils.helpers import get_msk_now

if TYPE_CHECKING:
    from .budget_service import TodayPlan

logger = logging.getLogger(__name__)

SOURCE_PLAN = "plan"
SOURCE_RECOVERY = "recovery"


async def _select_existing(session, telegram_id: int, plan_date: date) -> DailyLimit | None:
    result = await session.execute(
        select(DailyLimit).where(
            DailyLimit.telegram_id == telegram_id,
            DailyLimit.plan_date == plan_date,
        )
    )
    return result.scalar_one_or_none()


def _supports_on_conflict(dialect_name: str) -> bool:
    return dialect_name in {"sqlite", "postgresql"}


def _build_upsert_statement(
    dialect_name: str,
    telegram_id: int,
    plan_date: date,
    limit: float,
    source: str,
    now,
):
    if dialect_name == "sqlite":
        insert_fn = sqlite_insert
    elif dialect_name == "postgresql":
        insert_fn = pg_insert
    else:
        raise ValueError(f"Unsupported dialect for upsert: {dialect_name}")
    statement = insert_fn(DailyLimit).values(
        telegram_id=telegram_id,
        plan_date=plan_date,
        limit=float(limit),
        source=source,
        updated_at=now,
    )
    return statement.on_conflict_do_update(
        index_elements=[DailyLimit.telegram_id, DailyLimit.plan_date],
        set_={
            "limit": float(limit),
            "source": source,
            "updated_at": now,
        },
    )


async def _write_daily_limit_fallback(
    telegram_id: int,
    plan_date: date,
    limit: float,
    source: str,
) -> None:
    """Portable SELECT→INSERT retry for dialects without ON CONFLICT."""
    for attempt in (0, 1):
        async with async_session_maker() as session:
            attempted_insert = False
            try:
                row = await _select_existing(session, telegram_id, plan_date)
                attempted_insert = row is None
                if attempted_insert:
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
                return
            except IntegrityError:
                await session.rollback()
                if not attempted_insert or attempt == 1:
                    raise
                logger.info(
                    "daily_limits insert race for %s on %s, retrying as update",
                    telegram_id,
                    plan_date,
                )


async def _write_daily_limit(
    telegram_id: int,
    plan_date: date,
    limit: float,
    source: str,
) -> None:
    """Insert or update one day atomically where the dialect supports it."""
    async with async_session_maker() as session:
        bind = session.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""
        if _supports_on_conflict(dialect_name):
            now = get_msk_now()
            statement = _build_upsert_statement(
                dialect_name,
                telegram_id,
                plan_date,
                limit,
                source,
                now,
            )
            await session.execute(statement)
            await session.commit()
            return

    await _write_daily_limit_fallback(telegram_id, plan_date, limit, source)


async def upsert_daily_limit(
    telegram_id: int,
    plan_date: date,
    limit: float,
    source: str = SOURCE_PLAN,
) -> None:
    """Write the effective limit for ``plan_date``. Last write wins.

    SQLite and PostgreSQL use a single atomic ``INSERT … ON CONFLICT DO UPDATE``.
    Other dialects fall back to SELECT→INSERT with one retry on a PK race.
    """
    await _write_daily_limit(telegram_id, plan_date, limit, source)


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
    snapshot never stores a meaningless value. Only today can be resolved:
    the plan math depends on today's spend and remaining days.
    """
    return await _effective_daily_limit(telegram_id, budget, get_msk_now().date())


async def _effective_daily_limit(
    telegram_id: int,
    budget: Budget | None,
    today: date,
    plan: "TodayPlan | None" = None,
) -> tuple[float, str] | None:
    from .budget_service import (
        compute_today_plan,
        get_active_budget,
        get_base_daily_limit,
    )
    from .monthly_report import get_period_dates
    from .recovery_service import get_active_recovery

    if budget is None:
        budget = await get_active_budget(telegram_id)
    if budget is None:
        return None

    period_start, period_end = get_period_dates(budget)
    if not period_start.date() <= today <= period_end.date():
        return None
    if budget.days_remaining <= 0:
        return None
    base_limit = plan.base_limit if plan is not None else await get_base_daily_limit(budget)
    if base_limit <= 0:
        return None

    recovery = await get_active_recovery(telegram_id)
    if recovery is not None and recovery.budget_id == budget.id:
        return max(float(recovery.target), 0.0), SOURCE_RECOVERY

    today_plan = plan if plan is not None else await compute_today_plan(telegram_id, budget)
    return max(float(today_plan.plan_today), 0.0), SOURCE_PLAN


async def refresh_daily_limit(
    telegram_id: int,
    budget: Budget | None = None,
    plan: "TodayPlan | None" = None,
) -> tuple[float, str] | None:
    """Snapshot today's effective limit. Never raises into the caller.

    ``plan`` lets the caller reuse an already computed ``TodayPlan`` so the
    status/morning render does not run the canonical chain twice. Returns the
    effective ``(limit, source)`` when a snapshot was written, otherwise
    ``None``.
    """
    try:
        plan_date = get_msk_now().date()
        effective = await _effective_daily_limit(telegram_id, budget, plan_date, plan)
        if effective is None:
            return None
        limit, source = effective
        await upsert_daily_limit(telegram_id, plan_date, limit, source)
        return effective
    except Exception:
        logger.warning("Failed to refresh daily limit for %s", telegram_id, exc_info=True)
        return None


async def refresh_all_daily_limits() -> int:
    """Snapshot today's limit for every user with a budget. Returns users seen."""
    async with async_session_maker() as session:
        result = await session.execute(select(Budget.telegram_id).distinct())
        telegram_ids = list(result.scalars().all())

    for telegram_id in telegram_ids:
        await refresh_daily_limit(telegram_id)
    return len(telegram_ids)
