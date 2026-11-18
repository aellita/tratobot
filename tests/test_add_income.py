from unittest.mock import AsyncMock, MagicMock, patch

from src.bot.handlers.menu import save_add_income
from src.db.models.models import Budget, User
from src.services.budget_service import (
    add_income,
    get_active_budget,
    month_for_period_start,
    save_budget,
    update_budget_field,
)
from src.utils import phrases
from src.utils.helpers import get_msk_now


def _make_message(text: str, user_id: int = 1001) -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.from_user.id = user_id
    msg.from_user.first_name = "Test"
    msg.from_user.username = "testuser"
    msg.chat.id = user_id
    msg.message_id = 1
    msg.answer = AsyncMock(return_value=msg)
    return msg


def _make_state() -> AsyncMock:
    state = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    return state


def _seed_budget(db_session, **kwargs) -> Budget:
    budget = Budget(
        telegram_id=1001,
        month=get_msk_now().strftime("%Y-%m"),
        total_income=kwargs.get("total_income", 100000.0),
        mandatory_payments=kwargs.get("mandatory_payments", 30000.0),
        black_day_fund=kwargs.get("black_day_fund", 0.0),
        free_money=kwargs.get("free_money", 0.0),
        spent_at_recalc=kwargs.get("spent_at_recalc", 0.0),
        period_start_day=1,
    )
    return budget


async def _run(msg, state):
    with (
        patch("src.bot.handlers.menu.get_main_menu_keyboard", AsyncMock()),
        patch("src.bot.handlers.menu._handle_recovery_budget_change", AsyncMock()),
    ):
        await save_add_income(msg, state)


class TestAddedIncomeCounter:
    async def test_add_income_accumulates(self, db_session):
        db_session.add(User(telegram_id=1001))
        db_session.add(_seed_budget(db_session))
        await db_session.commit()

        await add_income(1001, 10000)
        await add_income(1001, 5000)

        budget = await get_active_budget(1001)
        assert budget.added_income == 15000.0
        assert budget.total_income == 115000.0

    async def test_save_budget_resets_added_income(self, db_session):
        db_session.add(User(telegram_id=1001))
        db_session.add(_seed_budget(db_session))
        await db_session.commit()

        await add_income(1001, 10000)
        await save_budget(
            1001,
            month_for_period_start(1),
            income=100000.0,
            mandatory=30000.0,
            black_day=0.0,
        )

        budget = await get_active_budget(1001)
        assert budget.added_income == 0.0

    async def test_mandatory_and_fund_edits_keep_added_income(self, db_session):
        db_session.add(User(telegram_id=1001))
        db_session.add(_seed_budget(db_session))
        await db_session.commit()

        await add_income(1001, 10000)
        await update_budget_field(1001, "mandatory_payments", 40000.0)
        await update_budget_field(1001, "black_day_fund", 5000.0)

        budget = await get_active_budget(1001)
        assert budget.mandatory_payments == 40000.0
        assert budget.black_day_fund == 5000.0
        assert budget.added_income == 10000.0


class TestAddIncome:
    async def test_adds_to_total_income_when_no_free_money(self, db_session):
        db_session.add(User(telegram_id=1001))
        db_session.add(_seed_budget(db_session))
        await db_session.commit()

        msg = _make_message("10000")
        state = _make_state()
        await _run(msg, state)

        text = msg.answer.call_args.kwargs["text"]
        assert "✅ Добавлено 10,000 ₽" in text
        assert "💰 Остаток: 80,000 ₽" in text
        assert "₽/день" in text

        budget = await get_active_budget(1001)
        assert budget.total_income == 110000.0
        assert budget.free_money == 0.0
        assert budget.added_income == 10000.0
        state.clear.assert_awaited()

    async def test_adds_to_free_money_when_it_exists(self, db_session):
        db_session.add(User(telegram_id=1001))
        db_session.add(_seed_budget(db_session, free_money=5000.0))
        await db_session.commit()

        msg = _make_message("10000")
        state = _make_state()
        await _run(msg, state)

        text = msg.answer.call_args.kwargs["text"]
        assert "✅ Добавлено 10,000 ₽" in text
        assert "💰 Остаток: 15,000 ₽" in text

        budget = await get_active_budget(1001)
        assert budget.free_money == 15000.0
        assert budget.total_income == 100000.0
        assert budget.added_income == 10000.0

    async def test_income_does_not_close_overrun(self, db_session):
        db_session.add(User(telegram_id=1001))
        db_session.add(
            _seed_budget(
                db_session,
                total_income=10000.0,
                mandatory_payments=20000.0,
                black_day_fund=0.0,
            )
        )
        await db_session.commit()

        msg = _make_message("5000")
        state = _make_state()
        await _run(msg, state)

        text = msg.answer.call_args.kwargs["text"]
        assert text == phrases.INCOME_ADDED_EMPTY.format(amount="5,000")

    async def test_no_budget_shows_honest_error(self, db_session):
        db_session.add(User(telegram_id=1001))
        await db_session.commit()

        msg = _make_message("10000")
        state = _make_state()
        await _run(msg, state)

        msg.answer.assert_awaited_once_with(phrases.ERR_NO_BUDGET)
        state.clear.assert_awaited()

    async def test_invalid_amount_keeps_state(self, db_session):
        db_session.add(User(telegram_id=1001))
        db_session.add(_seed_budget(db_session))
        await db_session.commit()

        msg = _make_message("abc")
        state = _make_state()

        with patch("src.bot.handlers.menu.handle_invalid_input", AsyncMock()) as invalid:
            await save_add_income(msg, state)

        invalid.assert_awaited()
        state.clear.assert_not_awaited()
