from datetime import date, timedelta

from src.db.models.models import Budget, User
from src.services.budget_service import delete_active_budget, delete_all_budgets
from src.services.daily_limits import get_daily_limits, upsert_daily_limit
from src.utils.helpers import get_msk_now


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
