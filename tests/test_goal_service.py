from src.db.models.models import Wishlist
from src.services.goal_service import add_spare_change_to_goal, deduct_from_goal, get_active_goal


class TestAddSpareChangeToGoal:
    async def test_adds_to_existing_goal(self, db_session, test_goal):
        new_total, name = await add_spare_change_to_goal(99999, 500.0)
        assert new_total == 10500.0
        assert name == "PS5"

    async def test_adds_zero_spare_change(self, db_session, test_goal):
        new_total, name = await add_spare_change_to_goal(99999, 0.0)
        assert new_total == 10000.0

    async def test_creates_goal_from_budget_when_no_goal_exists(self, db_session, test_budget):
        goal = await get_active_goal(99999)
        assert goal is None

        new_total, name = await add_spare_change_to_goal(99999, 1500.0)
        assert new_total == 1500.0
        assert name == "PS5"

        goal = await get_active_goal(99999)
        assert goal is not None
        assert goal.current_amount == 1500.0

    async def test_creates_goal_with_defaults_when_no_budget(self, db_session, test_user):
        new_total, name = await add_spare_change_to_goal(99999, 2000.0)
        assert new_total == 2000.0
        assert name == "Хотелка"

    async def test_accumulates_multiple_additions(self, db_session, test_goal):
        await add_spare_change_to_goal(99999, 500.0)
        new_total, name = await add_spare_change_to_goal(99999, 300.0)
        assert new_total == 10800.0

    async def test_very_large_spare_change(self, db_session, test_goal):
        new_total, name = await add_spare_change_to_goal(99999, 1_000_000.0)
        assert new_total == 1_010_000.0

    async def test_negative_spare_change_reduces_goal(self, db_session, test_goal):
        new_total, name = await add_spare_change_to_goal(99999, -500.0)
        assert new_total == 9500.0

    async def test_does_not_affect_inactive_goals(self, db_session, test_user):
        goal = Wishlist(
            telegram_id=99999,
            name="Old Goal",
            target_amount=10000.0,
            current_amount=5000.0,
            is_active=False,
        )
        db_session.add(goal)
        await db_session.commit()

        new_total, name = await add_spare_change_to_goal(99999, 1000.0)
        assert name == "Хотелка"


class TestDeductFromGoal:
    async def test_deducts_partial_amount(self, db_session, test_goal):
        result = await deduct_from_goal(99999, 3000.0)
        assert result is not None
        deduction, remaining, name = result
        assert deduction == 3000.0
        assert remaining == 7000.0
        assert name == "PS5"

    async def test_deducts_exact_amount(self, db_session, test_goal):
        result = await deduct_from_goal(99999, 10000.0)
        assert result is not None
        deduction, remaining, name = result
        assert deduction == 10000.0
        assert remaining == 0.0

    async def test_deducts_more_than_available(self, db_session, test_goal):
        result = await deduct_from_goal(99999, 50000.0)
        assert result is not None
        deduction, remaining, name = result
        assert deduction == 10000.0
        assert remaining == 0.0

    async def test_returns_none_when_no_goal(self, db_session, test_user):
        result = await deduct_from_goal(99999, 1000.0)
        assert result is None

    async def test_returns_none_when_goal_is_zero(self, db_session, test_user):
        goal = Wishlist(
            telegram_id=99999,
            name="Empty Goal",
            target_amount=5000.0,
            current_amount=0.0,
            is_active=True,
        )
        db_session.add(goal)
        await db_session.commit()

        result = await deduct_from_goal(99999, 1000.0)
        assert result is None

    async def test_returns_none_when_goal_is_negative(self, db_session, test_user):
        goal = Wishlist(
            telegram_id=99999,
            name="Negative Goal",
            target_amount=5000.0,
            current_amount=-100.0,
            is_active=True,
        )
        db_session.add(goal)
        await db_session.commit()

        result = await deduct_from_goal(99999, 100.0)
        assert result is None

    async def test_zero_deduction_returns_zero(self, db_session, test_goal):
        result = await deduct_from_goal(99999, 0.0)
        assert result is not None
        deduction, remaining, name = result
        assert deduction == 0.0
        assert remaining == 10000.0

    async def test_negative_deduction_increases_goal(self, db_session, test_goal):
        result = await deduct_from_goal(99999, -500.0)
        assert result is not None
        deduction, remaining, name = result
        assert deduction == -500.0
        assert remaining == 10500.0

    async def test_ignores_inactive_goals(self, db_session, test_user):
        inactive = Wishlist(
            telegram_id=99999,
            name="Inactive Goal",
            target_amount=10000.0,
            current_amount=5000.0,
            is_active=False,
        )
        db_session.add(inactive)
        await db_session.commit()

        result = await deduct_from_goal(99999, 1000.0)
        assert result is None

    async def test_multiple_deductions(self, db_session, test_goal):
        await deduct_from_goal(99999, 3000.0)
        await deduct_from_goal(99999, 2000.0)
        goal = await get_active_goal(99999)
        assert goal.current_amount == 5000.0
