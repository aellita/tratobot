"""Per-day limit snapshots (G2).

Stores the effective daily limit the user actually lived by: ``plan_today``
or an active Recovery target. Last write for a given day wins; past days are
never rewritten by later reconciliations.
"""

import logging
from datetime import date

from sqlalchemy import select

from ..db.database import async_session_maker
from ..db.models.models import DailyLimit

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
