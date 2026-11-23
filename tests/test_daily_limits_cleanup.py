from datetime import date, datetime, timedelta

from src.db.models.models import Budget, User
from src.services.budget_service import (
    delete_active_budget,
    delete_all_budgets,
    update_budget_field,
)
from src.services.daily_limits import get_daily_limits, upsert_daily_limit
from src.utils.helpers import get_msk_now, period_dates


async def _seed_user(db_session, telegram_id: int):
    db_session.add(User(telegram_id=telegram_id))
    await db_session.commit()


async def _seed_current_budget(db_session, telegram_id: int):
    budget = Budget(
        telegram_id=telegram_id,
        month=get_msk_now().strftime("%Y-%m"),
        total_income=100000,
        mandatory_payments=0,
        black_day_fund=0,
        period_start_day=1,
    )
    db_session.add(budget)
    await db_session.commit()
    return budget


async def test_delete_all_budgets_wipes_all_snapshots(db_session):
    await _seed_user(db_session, 1001)
    await _seed_user(db_session, 2002)
    await _seed_current_budget(db_session, 1001)
    today = get_msk_now().date()
    await upsert_daily_limit(1001, today, 1000.0)
    await upsert_daily_limit(1001, today - timedelta(days=400), 900.0)
    await upsert_daily_limit(2002, today, 500.0)

    removed = await delete_all_budgets(1001)

    assert removed == 1
    assert await get_daily_limits(1001, today - timedelta(days=500), today) == {}
    assert (await get_daily_limits(2002, today, today))[today] == 500.0


async def test_delete_all_budgets_wipes_snapshots_without_budgets(db_session):
    await _seed_user(db_session, 1001)
    today = get_msk_now().date()
    await upsert_daily_limit(1001, today, 1000.0)

    removed = await delete_all_budgets(1001)

    assert removed == 0
    assert await get_daily_limits(1001, today, today) == {}


async def test_delete_active_budget_uses_its_own_period(db_session):
    await _seed_user(db_session, 1001)
    today = get_msk_now().date()
    budget = Budget(
        telegram_id=1001,
        month=today.strftime("%Y-%m"),
        total_income=100000,
        mandatory_payments=0,
        black_day_fund=0,
        period_start_day=today.day,
    )
    db_session.add(budget)
    await db_session.commit()
    period_start, period_end = period_dates(budget.month, budget.period_start_day)
    inside = period_end.date()
    before = period_start.date() - timedelta(days=1)
    await upsert_daily_limit(1001, inside, 1000.0)
    await upsert_daily_limit(1001, before, 900.0)

    removed = await delete_active_budget(1001)

    assert removed is True
    assert await get_daily_limits(1001, inside, inside) == {}
    assert await get_daily_limits(1001, before, before) == {before: 900.0}


async def test_delete_active_budget_wipes_only_its_period(db_session):
    await _seed_user(db_session, 1001)
    await _seed_user(db_session, 2002)
    await _seed_current_budget(db_session, 1001)
    today = get_msk_now().date()
    outside = date(2020, 1, 15)
    await upsert_daily_limit(1001, today, 1000.0)
    await upsert_daily_limit(1001, outside, 900.0)
    await upsert_daily_limit(2002, today, 500.0)

    removed = await delete_active_budget(1001)

    assert removed is True
    assert await get_daily_limits(1001, today, today) == {}
    assert await get_daily_limits(1001, outside, outside) == {outside: 900.0}
    assert (await get_daily_limits(2002, today, today))[today] == 500.0


async def test_delete_active_budget_without_budget_returns_false(db_session):
    await _seed_user(db_session, 3003)

    assert await delete_active_budget(3003) is False


async def test_period_start_change_keeps_snapshots_of_new_period(db_session, monkeypatch):
    fixed = datetime(2026, 11, 23, 12, 0, 0)
    monkeypatch.setattr("src.services.budget_service.get_msk_now", lambda: fixed)
    await _seed_user(db_session, 1001)
    db_session.add(
        Budget(
            telegram_id=1001,
            month="2026-11",
            total_income=100000,
            mandatory_payments=0,
            black_day_fund=0,
            period_start_day=1,
        )
    )
    db_session.add(
        Budget(
            telegram_id=1001,
            month="2026-10",
            total_income=100000,
            mandatory_payments=0,
            black_day_fund=0,
            period_start_day=1,
        )
    )
    await db_session.commit()
    outside = date(2026, 10, 20)
    inside = date(2026, 10, 27)
    await upsert_daily_limit(1001, outside, 111.0)
    await upsert_daily_limit(1001, inside, 222.0)

    await update_budget_field(1001, "period_start_day", 25)

    assert await get_daily_limits(1001, outside, outside) == {}
    assert await get_daily_limits(1001, inside, inside) == {inside: 222.0}
