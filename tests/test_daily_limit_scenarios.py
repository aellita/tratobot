from datetime import datetime

import pytest

from src.db.models.models import Budget
from src.services.budget_service import get_active_budget


def _make_budget(income=150000, mandatory=0, black_day=0, period_start=1, month="2026-09"):
    return Budget(
        telegram_id=1,
        month=month,
        total_income=income,
        mandatory_payments=mandatory,
        black_day_fund=black_day,
        free_money=0,
        period_start_day=period_start,
    )


def _patch_model_date(monkeypatch, dt):
    monkeypatch.setattr("src.db.models.models._msk_now", lambda: dt)


class TestDaysRemaining:
    def test_first_day_period_start_1(self, monkeypatch):
        _patch_model_date(monkeypatch, datetime(2026, 9, 1))
        assert _make_budget().days_remaining == 30

    def test_last_day_period_start_1(self, monkeypatch):
        _patch_model_date(monkeypatch, datetime(2026, 9, 30))
        assert _make_budget().days_remaining == 1

    def test_first_day_period_start_20(self, monkeypatch):
        _patch_model_date(monkeypatch, datetime(2026, 9, 20))
        assert _make_budget(period_start=20).days_remaining == 30

    def test_last_day_period_start_20(self, monkeypatch):
        _patch_model_date(monkeypatch, datetime(2026, 9, 19))
        assert _make_budget(period_start=20).days_remaining == 1

    def test_mid_period_start_1(self, monkeypatch):
        _patch_model_date(monkeypatch, datetime(2026, 9, 15))
        assert _make_budget().days_remaining == 16

    def test_mid_period_start_20(self, monkeypatch):
        _patch_model_date(monkeypatch, datetime(2026, 9, 25))
        assert _make_budget(period_start=20).days_remaining == 25


class TestDailyLimit:
    def test_start_of_period(self, monkeypatch):
        _patch_model_date(monkeypatch, datetime(2026, 9, 1))
        assert _make_budget(income=150000).daily_limit == pytest.approx(5000)

    def test_mid_period_does_not_change(self, monkeypatch):
        _patch_model_date(monkeypatch, datetime(2026, 9, 15))
        assert _make_budget(income=150000).daily_limit == pytest.approx(5000)

    def test_overspending_clamped_to_zero(self, monkeypatch):
        _patch_model_date(monkeypatch, datetime(2026, 9, 1))
        assert _make_budget(income=5000, mandatory=10000).daily_limit == 0

    def test_mandatory_and_black_day_reduce(self, monkeypatch):
        _patch_model_date(monkeypatch, datetime(2026, 9, 1))
        budget = _make_budget(income=150000, mandatory=30000, black_day=10000)
        assert budget.daily_limit == pytest.approx(110000 / 30)

    def test_last_day_still_uses_total_days(self, monkeypatch):
        _patch_model_date(monkeypatch, datetime(2026, 9, 30))
        assert _make_budget(income=150000).daily_limit == pytest.approx(5000)


class TestActiveBudgetPeriodBoundary:
    async def test_period_20_switches_at_boundary(self, db_session, monkeypatch):
        db_session.add(
            Budget(
                telegram_id=1001,
                month="2026-08",
                total_income=100000.0,
                period_start_day=20,
            )
        )
        db_session.add(
            Budget(
                telegram_id=1001,
                month="2026-09",
                total_income=200000.0,
                period_start_day=20,
            )
        )
        from src.db.models.models import User

        db_session.add(User(telegram_id=1001))
        await db_session.commit()

        monkeypatch.setattr(
            "src.services.budget_service.get_msk_now",
            lambda: datetime(2026, 9, 19),
        )
        old = await get_active_budget(1001)
        assert old.month == "2026-08"

        monkeypatch.setattr(
            "src.services.budget_service.get_msk_now",
            lambda: datetime(2026, 9, 20),
        )
        new = await get_active_budget(1001)
        assert new.month == "2026-09"


class TestBuildStatus:
    async def test_dl_pred_first_day(self, db_session, monkeypatch):
        from src.bot.handlers.menu import _build_status

        db_session.add(
            Budget(
                telegram_id=1001,
                month="2026-09",
                total_income=150000.0,
                period_start_day=1,
            )
        )
        from src.db.models.models import User

        db_session.add(User(telegram_id=1001))
        await db_session.commit()

        dt = datetime(2026, 9, 1)
        monkeypatch.setattr("src.db.models.models._msk_now", lambda: dt)
        monkeypatch.setattr("src.bot.handlers.menu.get_msk_now", lambda: dt)
        monkeypatch.setattr("src.services.budget_service.get_msk_now", lambda: dt)
        monkeypatch.setattr("src.services.expense_service.get_msk_now", lambda: dt)

        text, _ = await _build_status(1001)
        assert "Лимит 5,000 ₽/день" in text

    async def test_dl_pred_recalculates_after_spending(self, db_session, monkeypatch):
        from src.bot.handlers.menu import _build_status
        from src.db.models.models import Expense, User

        db_session.add(
            Budget(
                telegram_id=1001,
                month="2026-09",
                total_income=150000.0,
                period_start_day=1,
            )
        )
        db_session.add(User(telegram_id=1001))
        db_session.add(
            Expense(
                telegram_id=1001,
                amount=30000.0,
                description="аренда",
                date=datetime(2026, 9, 3),
            )
        )
        await db_session.commit()

        dt = datetime(2026, 9, 10)
        monkeypatch.setattr("src.db.models.models._msk_now", lambda: dt)
        monkeypatch.setattr("src.bot.handlers.menu.get_msk_now", lambda: dt)
        monkeypatch.setattr("src.services.budget_service.get_msk_now", lambda: dt)
        monkeypatch.setattr("src.services.expense_service.get_msk_now", lambda: dt)

        text, _ = await _build_status(1001)
        assert "Лимит 5,714 ₽/день" in text
