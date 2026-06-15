from datetime import UTC, datetime

import pytest

from src.db.models.models import Expense, User
from src.services.expense_service import (
    compute_rounding,
    get_current_period_expenses_sum,
)


class TestComputeRounding:
    def test_rounds_up_to_next_10(self):
        rounded, spare = compute_rounding(1.0, 10)
        assert rounded == 10.0
        assert spare == 9.0

    def test_rounds_up_to_next_100(self):
        rounded, spare = compute_rounding(310.0, 100)
        assert rounded == 400.0
        assert spare == 90.0

    def test_exact_multiple_no_spare(self):
        rounded, spare = compute_rounding(300.0, 10)
        assert rounded == 300.0
        assert spare == 0.0

    def test_exact_multiple_mode_100(self):
        rounded, spare = compute_rounding(500.0, 100)
        assert rounded == 500.0
        assert spare == 0.0

    def test_small_amount_rounds_to_mode(self):
        rounded, spare = compute_rounding(0.5, 10)
        assert rounded == 10.0
        assert spare == 9.5

    def test_large_amount_rounds_correctly(self):
        rounded, spare = compute_rounding(12345.0, 100)
        assert rounded == 12400.0
        assert spare == 55.0

    def test_zero_amount_returns_zero(self):
        rounded, spare = compute_rounding(0.0, 10)
        assert rounded == 0.0
        assert spare == 0.0

    def test_mode_1_rounds_to_integer(self):
        rounded, spare = compute_rounding(123.45, 1)
        assert rounded == 124.0
        assert spare == pytest.approx(0.55, rel=1e-9)

    def test_negative_amount_rounds_to_zero(self):
        rounded, spare = compute_rounding(-5.0, 10)
        assert rounded == 0.0
        assert spare == 5.0

    def test_float_precision_preserved(self):
        rounded, spare = compute_rounding(0.1, 10)
        assert rounded == 10.0
        assert spare == pytest.approx(9.9, rel=1e-9)

    def test_mode_larger_than_amount(self):
        rounded, spare = compute_rounding(3.0, 100)
        assert rounded == 100.0
        assert spare == 97.0

    def test_rounding_mode_10_edge(self):
        rounded, spare = compute_rounding(9.99, 10)
        assert rounded == 10.0
        assert spare == pytest.approx(0.01, rel=1e-9)


class TestGetCurrentPeriodExpensesSum:
    async def test_no_budget_returns_zero(self, db_session, test_user):
        total = await get_current_period_expenses_sum(99999)
        assert total == 0.0

    async def test_sums_expenses_in_current_period(self, db_session, test_budget):
        now = datetime.now(UTC)
        db_session.add(Expense(telegram_id=99999, amount=500.0, description="кофе", date=now))
        db_session.add(Expense(telegram_id=99999, amount=300.0, description="обед", date=now))
        await db_session.commit()

        total = await get_current_period_expenses_sum(99999)
        assert total == 800.0

    async def test_excludes_soft_deleted_expenses(self, db_session, test_budget):
        now = datetime.now(UTC)
        db_session.add(
            Expense(telegram_id=99999, amount=500.0, description="кофе", date=now, is_deleted=True)
        )
        db_session.add(Expense(telegram_id=99999, amount=300.0, description="обед", date=now))
        await db_session.commit()

        total = await get_current_period_expenses_sum(99999)
        assert total == 300.0

    async def test_excludes_other_users_expenses(self, db_session, test_budget):
        now = datetime.now(UTC)
        db_session.add(User(telegram_id=88888))
        db_session.add(
            Expense(telegram_id=88888, amount=9999.0, description="чужая трата", date=now)
        )
        db_session.add(Expense(telegram_id=99999, amount=500.0, description="своя трата", date=now))
        await db_session.commit()

        total = await get_current_period_expenses_sum(99999)
        assert total == 500.0

    async def test_no_expenses_returns_zero(self, db_session, test_budget):
        total = await get_current_period_expenses_sum(99999)
        assert total == 0.0

    async def test_with_many_expenses(self, db_session, test_budget):
        now = datetime.now(UTC)
        for i in range(10):
            db_session.add(
                Expense(
                    telegram_id=99999, amount=100.0 * (i + 1), description=f"expense {i}", date=now
                )
            )
        await db_session.commit()

        total = await get_current_period_expenses_sum(99999)
        assert total == 5500.0

    async def test_expense_outside_period_excluded(self, db_session, test_budget):
        now = datetime.now(UTC)
        far_future = now.replace(year=now.year + 5)
        db_session.add(Expense(telegram_id=99999, amount=500.0, description="current", date=now))
        db_session.add(
            Expense(telegram_id=99999, amount=9999.0, description="future", date=far_future)
        )
        await db_session.commit()

        total = await get_current_period_expenses_sum(99999)
        assert total == 500.0

    async def test_float_precision_maintained(self, db_session, test_budget):
        now = datetime.now(UTC)
        db_session.add(Expense(telegram_id=99999, amount=0.1, description="a", date=now))
        db_session.add(Expense(telegram_id=99999, amount=0.2, description="b", date=now))
        await db_session.commit()

        total = await get_current_period_expenses_sum(99999)
        assert total == pytest.approx(0.3, rel=1e-9)

    async def test_very_large_expense(self, db_session, test_budget):
        now = datetime.now(UTC)
        db_session.add(
            Expense(telegram_id=99999, amount=999_999_999.0, description="large", date=now)
        )
        await db_session.commit()

        total = await get_current_period_expenses_sum(99999)
        assert total == 999_999_999.0

    async def test_negative_expense_included(self, db_session, test_budget):
        now = datetime.now(UTC)
        db_session.add(Expense(telegram_id=99999, amount=500.0, description="positive", date=now))
        db_session.add(Expense(telegram_id=99999, amount=-200.0, description="refund", date=now))
        await db_session.commit()

        total = await get_current_period_expenses_sum(99999)
        assert total == 300.0


class TestSoftDeleteExpense:
    async def test_soft_delete_sets_flag(self, db_session, test_expense):
        from src.services.expense_service import soft_delete_expense

        result = await soft_delete_expense(99999, test_expense.id)
        assert result is not None
        assert result.is_deleted is True

        await db_session.refresh(test_expense)
        assert test_expense.is_deleted is True

    async def test_soft_delete_nonexistent(self):
        from src.services.expense_service import soft_delete_expense

        result = await soft_delete_expense(99999, 99999)
        assert result is None

    async def test_soft_delete_wrong_user(self, db_session, test_expense):
        from src.services.expense_service import soft_delete_expense

        result = await soft_delete_expense(88888, test_expense.id)
        assert result is None

    async def test_soft_delete_already_deleted(self, db_session, test_expense):
        from src.services.expense_service import soft_delete_expense

        test_expense.is_deleted = True
        await db_session.commit()

        result = await soft_delete_expense(99999, test_expense.id)
        assert result is None


class TestRestoreExpense:
    async def test_restore_clears_flag(self, db_session):
        from src.services.expense_service import restore_expense

        exp = Expense(telegram_id=99999, amount=500.0, description="тест", is_deleted=True)
        db_session.add(exp)
        await db_session.commit()
        exp_id = exp.id

        result = await restore_expense(99999, exp_id)
        assert result is not None
        assert result.is_deleted is False

    async def test_restore_nonexistent(self):
        from src.services.expense_service import restore_expense

        result = await restore_expense(99999, 99999)
        assert result is None

    async def test_restore_not_deleted(self, db_session, test_expense):
        from src.services.expense_service import restore_expense

        result = await restore_expense(99999, test_expense.id)
        assert result is None

    async def test_restore_wrong_user(self, db_session):
        from src.services.expense_service import restore_expense

        exp = Expense(telegram_id=99999, amount=500.0, description="тест", is_deleted=True)
        db_session.add(exp)
        await db_session.commit()

        result = await restore_expense(88888, exp.id)
        assert result is None


class TestUpdateExpenseAmount:
    async def test_update_amount(self, db_session, test_expense):
        from src.services.expense_service import update_expense_amount

        result = await update_expense_amount(99999, test_expense.id, 999.0)
        assert result is not None
        assert result.amount == 999.0

        await db_session.refresh(test_expense)
        assert test_expense.amount == 999.0

    async def test_update_nonexistent(self):
        from src.services.expense_service import update_expense_amount

        result = await update_expense_amount(99999, 99999, 100.0)
        assert result is None

    async def test_update_wrong_user(self, db_session, test_expense):
        from src.services.expense_service import update_expense_amount

        result = await update_expense_amount(88888, test_expense.id, 100.0)
        assert result is None

    async def test_update_zero_amount(self, db_session, test_expense):
        from src.services.expense_service import update_expense_amount

        result = await update_expense_amount(99999, test_expense.id, 0.0)
        assert result is not None
        assert result.amount == 0.0

    async def test_update_deleted_expense_fails(self, db_session):
        from src.services.expense_service import update_expense_amount

        exp = Expense(telegram_id=99999, amount=500.0, description="тест", is_deleted=True)
        db_session.add(exp)
        await db_session.commit()

        result = await update_expense_amount(99999, exp.id, 999.0)
        assert result is None
