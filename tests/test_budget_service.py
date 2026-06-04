from datetime import datetime

import pytest

from src.db.models.models import Budget, User
from src.services.budget_service import (
    get_active_budget,
    reconcile_budget_with_reality,
    update_budget_field,
)


class TestGetActiveBudget:
    async def test_returns_current_month_budget(self, db_session):
        today = datetime.now()
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
        today = datetime.now()
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
        today = datetime.now()
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
        today = datetime.now()
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
        today = datetime.now()
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
        today = datetime.now()
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

        assert money_for_life == 40000.0
        assert mandatory == 30000.0
        assert black_day == 10000.0
        assert daily_limit > 0
        assert days_left > 0

    async def test_returns_zeros_when_no_budget(self):
        result = await reconcile_budget_with_reality(1001, 50000.0)
        assert result == (0.0, 1, 0.0, 0.0, 0.0)

    async def test_no_free_money_after_mandatory_and_black_day(self, db_session):
        today = datetime.now()
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

        assert money_for_life == 0.0
        assert daily_limit == 0.0
        assert days_left > 0

    async def test_days_left_capped_to_one(self, db_session):
        today = datetime.now()
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
        today = datetime.now()
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

        _, _, money_for_life, _, _ = await reconcile_budget_with_reality(1001, 10000.0)
        assert money_for_life == 0.0

    async def test_very_large_balance(self, db_session):
        today = datetime.now()
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

    async def test_boundary_balance_equals_mandatory_plus_black_day(self, db_session):
        today = datetime.now()
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

        _, _, money_for_life, _, _ = await reconcile_budget_with_reality(1001, 40000.0)
        assert money_for_life == 0.0


class TestUpdateBudgetField:
    async def test_updates_valid_field(self, db_session):
        today = datetime.now()
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

    async def test_no_budget_no_error(self):
        await update_budget_field(1001, "total_income", 75000.0)

    async def test_invalid_field_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid budget field"):
            await update_budget_field(1001, "nonexistent_field", 100.0)

    async def test_empty_field_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid budget field"):
            await update_budget_field(1001, "", 100.0)

    async def test_updates_wishlist_name(self, db_session):
        today = datetime.now()
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
        today = datetime.now()
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
        today = datetime.now()
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
