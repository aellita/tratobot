from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from src.db.models.models import Budget, Expense, User
from src.utils import phrases


def _freeze(monkeypatch, dt):
    monkeypatch.setattr("src.db.models.models._msk_now", lambda: dt)
    monkeypatch.setattr("src.bot.handlers.menu.get_msk_now", lambda: dt)
    monkeypatch.setattr("src.services.budget_service.get_msk_now", lambda: dt)
    monkeypatch.setattr("src.services.expense_service.get_msk_now", lambda: dt)


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


async def _seed_budget(
    db_session,
    *,
    total_income: float = 100000.0,
    mandatory_payments: float = 30000.0,
    free_money: float = 0.0,
    month: str = "2026-09",
    expenses: tuple[tuple[float, datetime], ...] = (),
) -> None:
    db_session.add(User(telegram_id=1001))
    db_session.add(
        Budget(
            telegram_id=1001,
            month=month,
            total_income=total_income,
            mandatory_payments=mandatory_payments,
            black_day_fund=0.0,
            free_money=free_money,
            spent_at_recalc=0.0,
            period_start_day=1,
        )
    )
    for amount, date in expenses:
        db_session.add(
            Expense(
                telegram_id=1001,
                amount=amount,
                description="траты",
                date=date,
            )
        )
    await db_session.commit()


async def _run_amount(amount: str):
    msg = _make_message(amount)
    state = _make_state()
    with (
        patch("src.bot.handlers.menu.get_main_menu_keyboard", AsyncMock()),
        patch("src.bot.handlers.menu._handle_recovery_budget_change", AsyncMock()),
    ):
        from src.bot.handlers.menu import save_add_income

        await save_add_income(msg, state)
    return msg.answer.call_args.kwargs["text"], state


class TestIncomeMessage:
    async def test_full_template_with_free_today_and_tomorrow(self, db_session, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 9, 14))
        await _seed_budget(db_session)

        text, state = await _run_amount("10000")

        assert text == (
            "✅ Добавлено 10,000 ₽\n"
            "💰 Остаток: 80,000 ₽\n"
            "Сегодня свободно: 4,705 ₽\n"
            "Завтра: 5,000 ₽/день"
        )
        state.clear.assert_awaited()

    async def test_today_spending_reduces_free_and_tomorrow(self, db_session, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 9, 14))
        await _seed_budget(
            db_session,
            expenses=((2000.0, datetime(2026, 9, 14)),),
        )

        text, _ = await _run_amount("10000")

        assert "💰 Остаток: 78,000 ₽" in text
        assert "Сегодня свободно: 2,705 ₽" in text
        assert "Завтра: 4,875 ₽/день" in text

    async def test_overrun_keeps_full_template_with_zeros(self, db_session, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 9, 14))
        await _seed_budget(db_session, total_income=10000.0, mandatory_payments=20000.0)

        text, _ = await _run_amount("5000")

        assert text == (
            "✅ Добавлено 5,000 ₽\n💰 Остаток: 0 ₽\nСегодня свободно: 0 ₽\nЗавтра: 0 ₽/день"
        )

    async def test_last_day_shows_zero_tomorrow(self, db_session, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 9, 30))
        await _seed_budget(db_session)

        text, _ = await _run_amount("5000")

        assert text == (
            "✅ Добавлено 5,000 ₽\n"
            "💰 Остаток: 75,000 ₽\n"
            "Сегодня свободно: 75,000 ₽\n"
            "Завтра: 0 ₽/день"
        )

    def test_old_short_variants_removed(self):
        assert not hasattr(phrases, "INCOME_ADDED_LAST_DAY")
        assert not hasattr(phrases, "INCOME_ADDED_EMPTY")
