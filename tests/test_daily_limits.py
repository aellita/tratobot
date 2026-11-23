from datetime import date, timedelta

import pytest
from sqlalchemy import select

from src.db.models.models import Budget, DailyLimit, User
from src.services.budget_service import (
    add_income,
    apply_reconciliation,
    save_budget,
    update_budget_field,
)
from src.services.daily_limits import (
    SOURCE_PLAN,
    SOURCE_RECOVERY,
    get_daily_limits,
    get_effective_daily_limit,
    refresh_all_daily_limits,
    refresh_daily_limit,
    upsert_daily_limit,
)
from src.services.recovery_service import (
    complete_recovery,
    create_recovery,
    stop_recovery,
    update_recovery_days,
)
from src.utils.helpers import get_msk_now


def _today() -> date:
    return get_msk_now().date()



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


class TestGetEffectiveDailyLimit:
    async def test_none_without_budget(self, db_session):
        await _seed_user(db_session, 6006)

        assert await get_effective_daily_limit(6006) is None

    async def test_returns_plan_by_default(self, db_session, test_budget):
        limit, source = await get_effective_daily_limit(99999)

        assert source == SOURCE_PLAN
        assert limit > 0

    async def test_recovery_target_wins(self, db_session, test_budget):
        await create_recovery(99999, test_budget.id, 1000, 300, 10, 5000)

        limit, source = await get_effective_daily_limit(99999)

        assert (limit, source) == (300.0, SOURCE_RECOVERY)

    async def test_none_when_base_limit_zero(self, db_session):
        await _seed_user(db_session, 3003)
        db_session.add(
            Budget(
                telegram_id=3003,
                month=get_msk_now().strftime("%Y-%m"),
                total_income=0,
                mandatory_payments=0,
                black_day_fund=0,
                period_start_day=1,
            )
        )
        await db_session.commit()

        assert await get_effective_daily_limit(3003) is None

    async def test_none_when_period_is_over(self, db_session):
        await _seed_user(db_session, 4004)
        old_budget = Budget(
            telegram_id=4004,
            month="2020-01",
            total_income=100000,
            mandatory_payments=0,
            black_day_fund=0,
            period_start_day=1,
        )
        db_session.add(old_budget)
        await db_session.commit()

        assert await get_effective_daily_limit(4004, old_budget) is None


class TestRefreshDailyLimit:
    async def test_writes_today_from_plan(self, db_session, test_budget):
        await refresh_daily_limit(99999)

        limits = await get_daily_limits(99999, _today(), _today())

        assert limits[_today()] > 0

    async def test_last_write_wins(self, db_session, test_budget):
        await upsert_daily_limit(99999, _today(), 1.0)
        await refresh_daily_limit(99999)

        limits = await get_daily_limits(99999, _today(), _today())

        assert limits[_today()] != 1.0

    async def test_does_not_touch_past_days(self, db_session, test_budget):
        yesterday = _today() - timedelta(days=1)
        await upsert_daily_limit(99999, yesterday, 111.0)

        await refresh_daily_limit(99999)

        limits = await get_daily_limits(99999, yesterday, _today())
        assert limits[yesterday] == 111.0
        assert _today() in limits

    async def test_skips_user_without_budget(self, db_session):
        await _seed_user(db_session, 6006)

        await refresh_daily_limit(6006)

        assert await get_daily_limits(6006, _today(), _today()) == {}

    async def test_writes_recovery_target(self, db_session, test_budget):
        await create_recovery(99999, test_budget.id, 1000, 300, 10, 5000)

        await refresh_daily_limit(99999)

        rows = await _rows(db_session)
        assert rows[-1].limit == 300.0
        assert rows[-1].source == SOURCE_RECOVERY

    async def test_refresh_all_covers_active_budgets_only(self, db_session, test_budget):
        await _seed_user(db_session, 6006)

        seen = await refresh_all_daily_limits()

        assert seen == 1
        assert _today() in await get_daily_limits(99999, _today(), _today())
        assert await get_daily_limits(6006, _today(), _today()) == {}


class TestPlanMutationTriggers:
    async def test_add_income_refreshes_today(self, db_session, test_budget):
        await refresh_daily_limit(99999)
        before = (await get_daily_limits(99999, _today(), _today()))[_today()]

        await add_income(99999, 10000)

        after = (await get_daily_limits(99999, _today(), _today()))[_today()]
        assert after > before

    async def test_reconciliation_refreshes_today(self, db_session, test_budget):
        await refresh_daily_limit(99999)
        before = (await get_daily_limits(99999, _today(), _today()))[_today()]

        await apply_reconciliation(99999, 1000.0)

        after = (await get_daily_limits(99999, _today(), _today()))[_today()]
        assert after < before

    async def test_save_budget_writes_today(self, db_session):
        await _seed_user(db_session, 4004)

        await save_budget(
            4004,
            get_msk_now().strftime("%Y-%m"),
            income=50000,
            mandatory=0,
            black_day=0,
            period_start_day=1,
        )

        limits = await get_daily_limits(4004, _today(), _today())
        assert limits[_today()] > 0

    async def test_update_budget_field_refreshes_today(self, db_session, test_budget):
        await refresh_daily_limit(99999)
        before = (await get_daily_limits(99999, _today(), _today()))[_today()]

        await update_budget_field(99999, "total_income", 200000.0)

        after = (await get_daily_limits(99999, _today(), _today()))[_today()]
        assert after > before


class TestRecoveryMutationTriggers:
    async def test_create_recovery_writes_target(self, db_session, test_budget):
        await create_recovery(99999, test_budget.id, 1000, 300, 10, 5000)

        rows = await _rows(db_session)
        assert [(row.limit, row.source) for row in rows] == [(300.0, SOURCE_RECOVERY)]

    async def test_stop_recovery_restores_plan(self, db_session, test_budget):
        await refresh_daily_limit(99999)
        plan_limit = (await get_daily_limits(99999, _today(), _today()))[_today()]
        await create_recovery(99999, test_budget.id, 1000, 300, 10, 5000)

        await stop_recovery(99999)

        rows = await _rows(db_session)
        assert rows[-1].source == SOURCE_PLAN
        assert rows[-1].limit == pytest.approx(plan_limit)

    async def test_complete_recovery_restores_plan(self, db_session, test_budget):
        await refresh_daily_limit(99999)
        plan_limit = (await get_daily_limits(99999, _today(), _today()))[_today()]
        await create_recovery(99999, test_budget.id, 1000, 300, 10, 5000)

        await complete_recovery(99999, "early_success")

        rows = await _rows(db_session)
        assert rows[-1].source == SOURCE_PLAN
        assert rows[-1].limit == pytest.approx(plan_limit)

    async def test_update_recovery_days_keeps_target(self, db_session, test_budget):
        await create_recovery(99999, test_budget.id, 1000, 300, 10, 5000)

        await update_recovery_days(99999, 5)

        rows = await _rows(db_session)
        assert rows[-1].limit == 300.0
        assert rows[-1].source == SOURCE_RECOVERY
