from datetime import date

from sqlalchemy import select

from src.db.models.models import DailyLimit, User
from src.services.daily_limits import (
    SOURCE_PLAN,
    SOURCE_RECOVERY,
    get_daily_limits,
    upsert_daily_limit,
)


async def _seed_user(db_session, telegram_id: int):
    db_session.add(User(telegram_id=telegram_id))
    await db_session.commit()


async def _rows(db_session) -> list[DailyLimit]:
    result = await db_session.execute(select(DailyLimit).order_by(DailyLimit.plan_date))
    return list(result.scalars().all())


class TestUpsertDailyLimit:
    async def test_inserts_new_row(self, db_session):
        await _seed_user(db_session, 1001)

        await upsert_daily_limit(1001, date(2026, 11, 20), 5000.0)

        rows = await _rows(db_session)
        assert len(rows) == 1
        assert rows[0].telegram_id == 1001
        assert rows[0].plan_date == date(2026, 11, 20)
        assert rows[0].limit == 5000.0
        assert rows[0].source == SOURCE_PLAN
        assert rows[0].updated_at is not None

    async def test_last_write_wins(self, db_session):
        await _seed_user(db_session, 1001)

        await upsert_daily_limit(1001, date(2026, 11, 20), 5000.0)
        await upsert_daily_limit(1001, date(2026, 11, 20), 7500.0)

        rows = await _rows(db_session)
        assert len(rows) == 1
        assert rows[0].limit == 7500.0

    async def test_last_write_wins_source(self, db_session):
        await _seed_user(db_session, 1001)

        await upsert_daily_limit(1001, date(2026, 11, 20), 5000.0, source=SOURCE_PLAN)
        await upsert_daily_limit(1001, date(2026, 11, 20), 3000.0, source=SOURCE_RECOVERY)

        rows = await _rows(db_session)
        assert len(rows) == 1
        assert rows[0].limit == 3000.0
        assert rows[0].source == SOURCE_RECOVERY

    async def test_zero_limit_is_written(self, db_session):
        await _seed_user(db_session, 1001)

        await upsert_daily_limit(1001, date(2026, 11, 20), 0.0)

        rows = await _rows(db_session)
        assert len(rows) == 1
        assert rows[0].limit == 0.0

    async def test_keeps_separate_rows_per_day(self, db_session):
        await _seed_user(db_session, 1001)

        await upsert_daily_limit(1001, date(2026, 11, 20), 5000.0)
        await upsert_daily_limit(1001, date(2026, 11, 21), 6000.0)

        rows = await _rows(db_session)
        assert len(rows) == 2
        assert [row.limit for row in rows] == [5000.0, 6000.0]


class TestGetDailyLimits:
    async def test_returns_range_inclusive(self, db_session):
        await _seed_user(db_session, 1001)
        for day in range(19, 23):
            await upsert_daily_limit(1001, date(2026, 11, day), float(day * 100))

        result = await get_daily_limits(1001, date(2026, 11, 20), date(2026, 11, 21))

        assert result == {
            date(2026, 11, 20): 2000.0,
            date(2026, 11, 21): 2100.0,
        }

    async def test_single_day_range(self, db_session):
        await _seed_user(db_session, 1001)
        await upsert_daily_limit(1001, date(2026, 11, 20), 5000.0)

        result = await get_daily_limits(1001, date(2026, 11, 20), date(2026, 11, 20))

        assert result == {date(2026, 11, 20): 5000.0}

    async def test_empty_when_no_rows(self, db_session):
        await _seed_user(db_session, 1001)

        result = await get_daily_limits(1001, date(2026, 11, 1), date(2026, 11, 30))

        assert result == {}

    async def test_scoped_by_user(self, db_session):
        await _seed_user(db_session, 1001)
        await _seed_user(db_session, 2002)
        await upsert_daily_limit(1001, date(2026, 11, 20), 5000.0)
        await upsert_daily_limit(2002, date(2026, 11, 20), 9000.0)

        result = await get_daily_limits(1001, date(2026, 11, 1), date(2026, 11, 30))

        assert result == {date(2026, 11, 20): 5000.0}

    async def test_inverted_range_returns_empty(self, db_session):
        await _seed_user(db_session, 1001)
        await upsert_daily_limit(1001, date(2026, 11, 20), 5000.0)

        result = await get_daily_limits(1001, date(2026, 11, 21), date(2026, 11, 20))

        assert result == {}
