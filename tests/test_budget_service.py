from datetime import datetime

import pytest
from sqlalchemy import select

from src.db.models.models import Budget, User
from src.services.budget_service import (
    NoActiveBudgetError,
    delete_active_budget,
    get_active_budget,
    month_for_period_start,
    reconcile_budget_with_reality,
    update_budget_field,
)
from src.utils.helpers import get_msk_now


class TestGetActiveBudget:
    async def test_returns_current_month_budget(self, db_session):
        today = get_msk_now()
        budget = Budget(
            telegram_id=1001,
            month=today.strftime("%Y-%m"),
            total_income=50000.0,
            period_start_day=1,
        )
        db_session.add(User(telegram_id=1001))
        db_session.add(budget)
        await db_session.commit()

        result = await get_active_budget(1001)
        assert result is not None
        assert result.telegram_id == 1001
        assert result.total_income == 50000.0

    async def test_returns_none_when_no_budget(self):
        result = await get_active_budget(1001)
        assert result is None

    async def test_returns_none_when_no_matching_period(self, db_session):
        today = get_msk_now()
        last_month_num = today.month - 1 if today.month > 1 else 12
        last_year = today.year if today.month > 1 else today.year - 1
        last_month_str = f"{last_year:04d}-{last_month_num:02d}"

        budget = Budget(
            telegram_id=1001,
            month=last_month_str,
            total_income=50000.0,
            period_start_day=1,
        )
        db_session.add(User(telegram_id=1001))
        db_session.add(budget)
        await db_session.commit()

        result = await get_active_budget(1001)
        assert result is None

    async def test_picks_newer_budget_when_multiple_exist(self, db_session):
        today = get_msk_now()
        this_month = today.strftime("%Y-%m")
        last_month_num = today.month - 1 if today.month > 1 else 12
        last_year = today.year if today.month > 1 else today.year - 1
        last_month_str = f"{last_year:04d}-{last_month_num:02d}"

        db_session.add(User(telegram_id=1001))
        db_session.add(
            Budget(telegram_id=1001, month=last_month_str, total_income=30000.0, period_start_day=1)
        )
        db_session.add(
            Budget(telegram_id=1001, month=this_month, total_income=50000.0, period_start_day=1)
        )
        await db_session.commit()

        result = await get_active_budget(1001)
        assert result is not None
        assert result.total_income == 50000.0

    async def test_ignores_other_users_budgets(self, db_session):
        today = get_msk_now()
        db_session.add(User(telegram_id=1001))
        db_session.add(User(telegram_id=1002))
        db_session.add(
            Budget(
                telegram_id=1002,
                month=today.strftime("%Y-%m"),
                total_income=99999.0,
                period_start_day=1,
            )
        )
        await db_session.commit()

        result = await get_active_budget(1001)
        assert result is None

    async def test_empty_month_string_does_not_crash(self, db_session):
        db_session.add(User(telegram_id=1001))
        db_session.add(Budget(telegram_id=1001, month="", total_income=50000.0, period_start_day=1))
        await db_session.commit()

        result = await get_active_budget(1001)
        assert result is None

    async def test_very_large_telegram_id(self, db_session):
        today = get_msk_now()
        large_id = 10**15
        budget = Budget(
            telegram_id=large_id,
            month=today.strftime("%Y-%m"),
            total_income=50000.0,
            period_start_day=1,
        )
        db_session.add(User(telegram_id=large_id))
        db_session.add(budget)
        await db_session.commit()

        result = await get_active_budget(large_id)
        assert result is not None
        assert result.telegram_id == large_id


class TestReconcileBudgetWithReality:
    async def test_normal_case(self, db_session):
        today = get_msk_now()
        budget = Budget(
            telegram_id=1001,
            month=today.strftime("%Y-%m"),
            total_income=100000.0,
            mandatory_payments=30000.0,
            black_day_fund=10000.0,
            period_start_day=1,
        )
        db_session.add(User(telegram_id=1001))
        db_session.add(budget)
        await db_session.commit()

        (
            daily_limit,
            days_left,
            money_for_life,
            mandatory,
            black_day,
        ) = await reconcile_budget_with_reality(1001, 80000.0)

        assert money_for_life == 80000.0
        assert mandatory == 30000.0
        assert black_day == 10000.0
        assert daily_limit > 0
        assert days_left > 0

    async def test_returns_zeros_when_no_budget(self):
        result = await reconcile_budget_with_reality(1001, 50000.0)
        assert result == (0.0, 1, 0.0, 0.0, 0.0)

    async def test_balance_used_directly_for_money_for_life(self, db_session):
        today = get_msk_now()
        budget = Budget(
            telegram_id=1001,
            month=today.strftime("%Y-%m"),
            total_income=100000.0,
            mandatory_payments=80000.0,
            black_day_fund=20000.0,
            period_start_day=1,
        )
        db_session.add(User(telegram_id=1001))
        db_session.add(budget)
        await db_session.commit()

        (
            daily_limit,
            days_left,
            money_for_life,
            mandatory,
            black_day,
        ) = await reconcile_budget_with_reality(1001, 50000.0)

        assert money_for_life == 50000.0
        assert daily_limit > 0
        assert days_left > 0

    async def test_days_left_capped_to_one(self, db_session):
        today = get_msk_now()
        budget = Budget(
            telegram_id=1001,
            month=today.strftime("%Y-%m"),
            total_income=100000.0,
            mandatory_payments=30000.0,
            black_day_fund=10000.0,
            period_start_day=today.day + 2 if today.day < 28 else 1,
        )
        db_session.add(User(telegram_id=1001))
        db_session.add(budget)
        await db_session.commit()

        daily_limit, days_left, money_for_life, _, _ = await reconcile_budget_with_reality(
            1001, 50000.0
        )

        assert days_left >= 1
        assert daily_limit >= 0

    async def test_negative_balance_clamped_to_zero(self, db_session):
        today = get_msk_now()
        budget = Budget(
            telegram_id=1001,
            month=today.strftime("%Y-%m"),
            total_income=100000.0,
            mandatory_payments=80000.0,
            black_day_fund=50000.0,
            period_start_day=1,
        )
        db_session.add(User(telegram_id=1001))
        db_session.add(budget)
        await db_session.commit()

        _, _, money_for_life, _, _ = await reconcile_budget_with_reality(1001, -100.0)
        assert money_for_life == 0.0

    async def test_very_large_balance(self, db_session):
        today = get_msk_now()
        budget = Budget(
            telegram_id=1001,
            month=today.strftime("%Y-%m"),
            total_income=1_000_000_000.0,
            mandatory_payments=0.0,
            black_day_fund=0.0,
            period_start_day=1,
        )
        db_session.add(User(telegram_id=1001))
        db_session.add(budget)
        await db_session.commit()

        daily_limit, _, money_for_life, _, _ = await reconcile_budget_with_reality(
            1001, 500_000_000.0
        )

        assert money_for_life == 500_000_000.0
        assert daily_limit > 0

    async def test_zero_balance_returns_zero_limit(self, db_session):
        today = get_msk_now()
        budget = Budget(
            telegram_id=1001,
            month=today.strftime("%Y-%m"),
            total_income=100000.0,
            mandatory_payments=30000.0,
            black_day_fund=10000.0,
            period_start_day=1,
        )
        db_session.add(User(telegram_id=1001))
        db_session.add(budget)
        await db_session.commit()

        daily_limit, _, money_for_life, _, _ = await reconcile_budget_with_reality(1001, 0.0)
        assert money_for_life == 0.0
        assert daily_limit == 0.0


class TestUpdateBudgetField:
    async def test_updates_valid_field(self, db_session):
        today = get_msk_now()
        budget = Budget(
            telegram_id=1001,
            month=today.strftime("%Y-%m"),
            total_income=50000.0,
            period_start_day=1,
        )
        db_session.add(User(telegram_id=1001))
        db_session.add(budget)
        await db_session.commit()

        await update_budget_field(1001, "total_income", 75000.0)

        result = await get_active_budget(1001)
        assert result.total_income == 75000.0

    async def test_no_budget_raises(self):
        with pytest.raises(NoActiveBudgetError):
            await update_budget_field(1001, "total_income", 75000.0)

    async def test_invalid_field_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid budget field"):
            await update_budget_field(1001, "nonexistent_field", 100.0)

    async def test_empty_field_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid budget field"):
            await update_budget_field(1001, "", 100.0)

    async def test_updates_wishlist_name(self, db_session):
        today = get_msk_now()
        budget = Budget(
            telegram_id=1001,
            month=today.strftime("%Y-%m"),
            wishlist_name="Old Name",
            period_start_day=1,
        )
        db_session.add(User(telegram_id=1001))
        db_session.add(budget)
        await db_session.commit()

        await update_budget_field(1001, "wishlist_name", "New Name")

        result = await get_active_budget(1001)
        assert result.wishlist_name == "New Name"

    async def test_updates_to_zero(self, db_session):
        today = get_msk_now()
        budget = Budget(
            telegram_id=1001,
            month=today.strftime("%Y-%m"),
            mandatory_payments=5000.0,
            period_start_day=1,
        )
        db_session.add(User(telegram_id=1001))
        db_session.add(budget)
        await db_session.commit()

        await update_budget_field(1001, "mandatory_payments", 0.0)

        result = await get_active_budget(1001)
        assert result.mandatory_payments == 0.0

    async def test_special_chars_in_wishlist_name(self, db_session):
        today = get_msk_now()
        budget = Budget(
            telegram_id=1001,
            month=today.strftime("%Y-%m"),
            period_start_day=1,
        )
        db_session.add(User(telegram_id=1001))
        db_session.add(budget)
        await db_session.commit()

        await update_budget_field(1001, "wishlist_name", "<script>alert('xss')</script>")

        result = await get_active_budget(1001)
        assert "<script>" in result.wishlist_name


# =============================================================================
# B11 — правки активного бюджета, месяц периода, base_daily_limit
# =============================================================================


def _freeze(monkeypatch, dt):
    monkeypatch.setattr("src.services.budget_service.get_msk_now", lambda: dt)
    monkeypatch.setattr("src.utils.helpers.get_msk_now", lambda: dt)
    monkeypatch.setattr("src.db.models.models._msk_now", lambda: dt)


class TestMonthForPeriodStart:
    @pytest.mark.parametrize(
        ("today", "start", "expected"),
        [
            (datetime(2026, 9, 10), 1, "2026-09"),
            (datetime(2026, 9, 10), 10, "2026-09"),
            (datetime(2026, 9, 5), 20, "2026-08"),
            (datetime(2026, 9, 20), 20, "2026-09"),
            (datetime(2026, 1, 5), 20, "2025-12"),
        ],
    )
    def test_month(self, today, start, expected):
        assert month_for_period_start(start, today) == expected

    def test_uses_current_time_by_default(self):
        today = get_msk_now()
        assert month_for_period_start(1) == today.strftime("%Y-%m")


class TestUpdateTargetsActiveBudget:
    async def test_updates_previous_month_budget_when_period_started_there(
        self, db_session, monkeypatch
    ):
        _freeze(monkeypatch, datetime(2026, 2, 5))
        db_session.add(User(telegram_id=1001))
        db_session.add(
            Budget(
                telegram_id=1001,
                month="2026-01",
                total_income=50000.0,
                period_start_day=20,
            )
        )
        await db_session.commit()

        updated = await update_budget_field(1001, "total_income", 70000.0)

        assert updated.month == "2026-01"
        assert updated.total_income == 70000.0

        db_session.expire_all()
        result = await db_session.execute(select(Budget).where(Budget.telegram_id == 1001))
        budgets = result.scalars().all()
        assert len(budgets) == 1
        assert budgets[0].total_income == 70000.0

    async def test_does_not_touch_current_month_row_when_active_is_previous(
        self, db_session, monkeypatch
    ):
        _freeze(monkeypatch, datetime(2026, 2, 5))
        db_session.add(User(telegram_id=1001))
        db_session.add(
            Budget(
                telegram_id=1001,
                month="2026-01",
                total_income=50000.0,
                period_start_day=20,
            )
        )
        db_session.add(
            Budget(
                telegram_id=1001,
                month="2026-02",
                total_income=90000.0,
                period_start_day=20,
            )
        )
        await db_session.commit()

        await update_budget_field(1001, "free_money", 1234.0)

        db_session.expire_all()
        result = await db_session.execute(
            select(Budget).where(Budget.telegram_id == 1001).order_by(Budget.month)
        )
        budgets = {b.month: b for b in result.scalars().all()}
        assert budgets["2026-01"].free_money == 1234.0
        assert budgets["2026-02"].free_money == 0.0


class TestBaseLimitRecalc:
    async def _seed(self, db_session, **kwargs):
        db_session.add(User(telegram_id=1001))
        db_session.add(
            Budget(
                telegram_id=1001,
                month="2026-09",
                total_income=kwargs.get("total_income", 90000.0),
                mandatory_payments=kwargs.get("mandatory_payments", 0.0),
                black_day_fund=kwargs.get("black_day_fund", 0.0),
                period_start_day=1,
            )
        )
        await db_session.commit()

    async def test_total_income(self, db_session, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 9, 1))
        await self._seed(db_session)

        updated = await update_budget_field(1001, "total_income", 150000.0)

        assert updated.base_daily_limit == pytest.approx(5000.0)

    async def test_mandatory_payments(self, db_session, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 9, 1))
        await self._seed(db_session, total_income=150000.0)

        updated = await update_budget_field(1001, "mandatory_payments", 30000.0)

        assert updated.base_daily_limit == pytest.approx(4000.0)

    async def test_black_day_fund(self, db_session, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 9, 1))
        await self._seed(db_session, total_income=150000.0)

        updated = await update_budget_field(1001, "black_day_fund", 30000.0)

        assert updated.base_daily_limit == pytest.approx(4000.0)

    async def test_free_money_does_not_change_base_limit(self, db_session, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 9, 1))
        await self._seed(db_session, total_income=150000.0)
        base_before = (await get_active_budget(1001)).base_daily_limit

        updated = await update_budget_field(1001, "free_money", 10000.0)

        assert updated.base_daily_limit == pytest.approx(base_before)


class TestPeriodStartReanchor:
    async def test_moves_budget_to_previous_month(self, db_session, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 2, 5))
        db_session.add(User(telegram_id=1001))
        db_session.add(
            Budget(
                telegram_id=1001,
                month="2026-02",
                total_income=90000.0,
                period_start_day=1,
            )
        )
        await db_session.commit()

        updated = await update_budget_field(1001, "period_start_day", 20)

        assert updated.month == "2026-01"
        assert updated.period_start_day == 20

    async def test_keeps_current_month_when_start_already_passed(self, db_session, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 2, 25))
        db_session.add(User(telegram_id=1001))
        db_session.add(
            Budget(
                telegram_id=1001,
                month="2026-02",
                total_income=90000.0,
                period_start_day=1,
            )
        )
        await db_session.commit()

        updated = await update_budget_field(1001, "period_start_day", 20)

        assert updated.month == "2026-02"

    async def test_replaces_stale_budget_in_target_month(self, db_session, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 2, 5))
        db_session.add(User(telegram_id=1001))
        db_session.add(
            Budget(
                telegram_id=1001,
                month="2026-02",
                total_income=90000.0,
                period_start_day=1,
            )
        )
        db_session.add(
            Budget(
                telegram_id=1001,
                month="2026-01",
                total_income=10000.0,
                period_start_day=20,
            )
        )
        await db_session.commit()

        updated = await update_budget_field(1001, "period_start_day", 20)

        assert updated.month == "2026-01"
        assert updated.total_income == 90000.0

        db_session.expire_all()
        result = await db_session.execute(select(Budget).where(Budget.telegram_id == 1001))
        budgets = result.scalars().all()
        assert len(budgets) == 1
        assert budgets[0].month == "2026-01"
        assert budgets[0].total_income == 90000.0


class TestDeleteActiveBudget:
    async def test_deletes_previous_month_active_budget(self, db_session, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 2, 5))
        db_session.add(User(telegram_id=1001))
        db_session.add(
            Budget(
                telegram_id=1001,
                month="2026-01",
                total_income=50000.0,
                period_start_day=20,
            )
        )
        await db_session.commit()

        assert await delete_active_budget(1001) is True

        db_session.expire_all()
        result = await db_session.execute(select(Budget).where(Budget.telegram_id == 1001))
        assert result.scalars().all() == []

    async def test_returns_false_when_no_budget(self):
        assert await delete_active_budget(1001) is False


class TestDeleteRecoverySafety:
    async def test_delete_all_budgets_removes_recovery_rows(self, db_session):
        from src.db.models.models import RecoveryState
        from src.services.budget_service import delete_all_budgets

        db_session.add(User(telegram_id=1001))
        budget = Budget(
            telegram_id=1001,
            month="2026-09",
            total_income=90000.0,
            period_start_day=1,
        )
        db_session.add(budget)
        await db_session.flush()
        db_session.add(
            RecoveryState(
                telegram_id=1001,
                budget_id=budget.id,
                status="stopped",
                baseline=9000.0,
                target=6000.0,
                total_days=5,
                initial_deficit=15000.0,
                initial_target=6000.0,
                initial_total_days=5,
            )
        )
        await db_session.commit()

        assert await delete_all_budgets(1001) == 1

        db_session.expire_all()
        budgets = (await db_session.execute(select(Budget))).scalars().all()
        recoveries = (await db_session.execute(select(RecoveryState))).scalars().all()
        assert budgets == []
        assert recoveries == []
