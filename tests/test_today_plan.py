import pytest

from src.db.models.models import Expense
from src.services.budget_service import (
    compute_today_plan,
    get_base_daily_limit,
    get_money_for_life,
    get_money_for_life_raw,
    get_period_spent,
    get_plan_today,
    get_spent_today_at_recalc,
)
from src.services.daily_limits import (
    SOURCE_PLAN,
    get_daily_limits,
    get_effective_daily_limit,
    refresh_daily_limit,
)
from src.services.expense_service import get_today_expenses_sum
from src.utils.helpers import get_msk_now


async def test_matches_canonical_functions(db_session, test_budget):
    today = get_msk_now()
    db_session.add(
        Expense(
            telegram_id=99999,
            amount=500.0,
            description="кофе",
            date=today.replace(hour=12, minute=0, second=0, microsecond=0),
        )
    )
    await db_session.commit()

    plan = await compute_today_plan(99999, test_budget)

    spent_period = await get_period_spent(99999, test_budget)
    spent_today = await get_today_expenses_sum(99999)
    expected = get_plan_today(
        get_money_for_life_raw(test_budget, spent_period),
        spent_today,
        test_budget.days_remaining,
        get_spent_today_at_recalc(test_budget),
    )

    assert plan.plan_today == pytest.approx(expected)
    assert plan.spent_today == 500.0
    assert plan.spent_period == 500.0
    assert plan.days_left == test_budget.days_remaining
    assert plan.base_limit == pytest.approx(await get_base_daily_limit(test_budget))
    assert plan.money_for_life == pytest.approx(get_money_for_life(test_budget, spent_period))
    assert plan.money_for_life_raw == pytest.approx(
        get_money_for_life_raw(test_budget, spent_period)
    )


async def test_empty_day(db_session, test_budget):
    plan = await compute_today_plan(99999, test_budget)

    assert plan.spent_today == 0.0
    assert plan.spent_period == 0.0
    assert plan.plan_today > 0
    assert plan.days_left > 0
    assert plan.base_limit > 0


async def test_snapshot_uses_same_plan(db_session, test_budget):
    today = get_msk_now().date()
    plan = await compute_today_plan(99999, test_budget)

    limit, source = await get_effective_daily_limit(99999)
    assert source == SOURCE_PLAN
    assert limit == pytest.approx(plan.plan_today)
    assert await get_daily_limits(99999, today, today) == {}

    await refresh_daily_limit(99999)

    stored = await get_daily_limits(99999, today, today)
    assert stored[today] == pytest.approx(plan.plan_today)


async def test_refresh_with_plan_skips_recompute(db_session, test_budget, monkeypatch):
    plan = await compute_today_plan(99999, test_budget)

    async def boom(*args, **kwargs):
        raise AssertionError("compute_today_plan must not run when a plan is passed")

    monkeypatch.setattr("src.services.budget_service.compute_today_plan", boom)

    effective = await refresh_daily_limit(99999, test_budget, plan)

    assert effective is not None
    assert effective[0] == pytest.approx(plan.plan_today)
    assert effective[1] == SOURCE_PLAN
