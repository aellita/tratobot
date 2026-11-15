from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import select

from src.bot.handlers.menu import _handle_recovery_budget_change
from src.db.models.models import Budget, RecoveryState, User
from src.services.recovery_service import (
    get_active_recovery,
    is_early_completion,
    recovery_day_number,
)
from src.utils import phrases


def _freeze(monkeypatch, dt: datetime):
    for target in [
        "src.db.models.models._msk_now",
        "src.bot.handlers.menu.get_msk_now",
        "src.services.budget_service.get_msk_now",
        "src.services.expense_service.get_msk_now",
        "src.services.recovery_service.get_msk_now",
        "src.utils.helpers.get_msk_now",
    ]:
        monkeypatch.setattr(target, lambda: dt)


def _message() -> MagicMock:
    msg = MagicMock()
    msg.answer = AsyncMock()
    return msg


class TestRecoveryDayNumber:
    def test_first_day_is_one(self):
        started = datetime(2026, 9, 14)
        assert recovery_day_number(started, datetime(2026, 9, 14)) == 1

    def test_counts_calendar_days(self):
        started = datetime(2026, 9, 10)
        assert recovery_day_number(started, datetime(2026, 9, 14)) == 5


class TestEarlyCompletion:
    def test_day_one_of_five_is_early(self):
        active = SimpleNamespace(started_at=datetime(2026, 9, 14), total_days=5)
        assert is_early_completion(active, datetime(2026, 9, 14)) is True

    def test_last_planned_day_is_not_early(self):
        active = SimpleNamespace(started_at=datetime(2026, 9, 10), total_days=5)
        assert is_early_completion(active, datetime(2026, 9, 14)) is False

    def test_after_plan_is_not_early(self):
        active = SimpleNamespace(started_at=datetime(2026, 9, 1), total_days=5)
        assert is_early_completion(active, datetime(2026, 9, 14)) is False


def test_early_phrase_says_early_and_keeps_baseline():
    text = phrases.RECOVERY_SUCCESS_EARLY.format(baseline=10000)
    assert "раньше срока" in text
    assert "10000" in text


async def _seed(
    db_session,
    *,
    started_at: datetime,
    total_days: int = 5,
    income: float = 200000.0,
) -> Budget:
    db_session.add(User(telegram_id=1001))
    budget = Budget(
        telegram_id=1001,
        month="2026-09",
        total_income=income,
        mandatory_payments=0.0,
        black_day_fund=0.0,
        period_start_day=1,
        base_daily_limit=10000.0,
    )
    db_session.add(budget)
    await db_session.flush()
    db_session.add(
        RecoveryState(
            telegram_id=1001,
            budget_id=budget.id,
            status="active",
            baseline=10000.0,
            target=7000.0,
            total_days=total_days,
            initial_deficit=15000.0,
            initial_target=7000.0,
            initial_total_days=total_days,
            started_at=started_at,
            created_at=started_at,
            updated_at=started_at,
        )
    )
    await db_session.commit()
    return budget


class TestIncomeDuringRecovery:
    async def test_day_one_success_closes_with_early_phrase(self, db_session, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 9, 14))
        await _seed(db_session, started_at=datetime(2026, 9, 14))

        msg = _message()
        await _handle_recovery_budget_change(1001, msg)

        msg.answer.assert_awaited_once()
        text = msg.answer.await_args.kwargs["text"]
        assert text == phrases.RECOVERY_SUCCESS_EARLY.format(baseline=10000)
        assert await get_active_recovery(1001) is None

        rs = (await db_session.execute(select(RecoveryState))).scalar_one()
        await db_session.refresh(rs)
        assert rs.status == "completed"
        assert rs.completion_reason == "early_success"

    async def test_on_time_success_uses_regular_phrase(self, db_session, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 9, 14))
        await _seed(db_session, started_at=datetime(2026, 9, 10), total_days=5)

        msg = _message()
        await _handle_recovery_budget_change(1001, msg)

        text = msg.answer.await_args.kwargs["text"]
        assert text == phrases.RECOVERY_BUDGET_DONE

        rs = (await db_session.execute(select(RecoveryState))).scalar_one()
        await db_session.refresh(rs)
        assert rs.status == "completed"
        assert rs.completion_reason == "budget_update"

    async def test_not_enough_income_shortens_and_keeps_recovery(self, db_session, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 9, 14))
        await _seed(db_session, started_at=datetime(2026, 9, 14), income=160000.0)

        msg = _message()
        await _handle_recovery_budget_change(1001, msg)

        text = msg.answer.await_args.kwargs["text"]
        assert "5 → 4" in text
        active = await get_active_recovery(1001)
        assert active is not None
        assert active.total_days == 4
