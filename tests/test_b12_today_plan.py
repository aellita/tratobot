from datetime import datetime

import pytest

from src.db.models.models import Budget, Expense, User
from src.services.budget_service import (
    get_free_today,
    get_overrun_today,
    get_plan_today,
)
from src.utils import phrases
from src.utils.helpers import period_total_days


def _freeze(monkeypatch, dt):
    monkeypatch.setattr("src.db.models.models._msk_now", lambda: dt)
    monkeypatch.setattr("src.bot.handlers.menu.get_msk_now", lambda: dt)
    monkeypatch.setattr("src.services.budget_service.get_msk_now", lambda: dt)
    monkeypatch.setattr("src.services.expense_service.get_msk_now", lambda: dt)


class TestTodayMath:
    def test_plan_is_morning_plan(self):
        # 150 134 осталось после сегодняшних 9 015, 17 дней
        assert get_plan_today(150134, 9015, 17) == pytest.approx(9361.7, abs=0.1)

    def test_free_today(self):
        plan = get_plan_today(150134, 9015, 17)
        assert get_free_today(plan, 9015) == pytest.approx(346.7, abs=0.1)

    def test_overrun_today(self):
        plan = get_plan_today(159137 - 18343, 18343, 17)
        assert plan == pytest.approx(9361.0)
        assert get_free_today(plan, 18343) == 0
        assert get_overrun_today(plan, 18343) == pytest.approx(8982.0)

    def test_plan_does_not_change_when_spending_grows(self):
        money = 159149 - 1000
        plan_before = get_plan_today(159149, 0, 18)
        plan_after = get_plan_today(money, 1000, 18)
        assert plan_after == pytest.approx(plan_before)

    def test_zero_days_left(self):
        assert get_plan_today(1000, 500, 0) == 0


class TestPeriodLength:
    @pytest.mark.parametrize(
        ("month", "start", "expected"),
        [
            ("2026-08", 20, 31),  # 20.08–19.09
            ("2026-09", 20, 30),  # 20.09–19.10
            ("2026-02", 20, 28),  # 20.02–19.03, не високосный
            ("2028-02", 20, 29),  # високосный
            ("2026-09", 1, 30),
            ("2026-02", 1, 28),
        ],
    )
    def test_period_total_days(self, month, start, expected):
        assert period_total_days(month, start) == expected

    def test_model_uses_period_start_month(self, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 9, 17))
        budget = Budget(telegram_id=1, month="2026-08", period_start_day=20)
        assert budget._period_total_days == 31


class TestStatusPlan:
    async def _status(self, db_session, monkeypatch, *, today, income, spent_today):
        _freeze(monkeypatch, today)
        db_session.add(User(telegram_id=1001))
        db_session.add(
            Budget(
                telegram_id=1001,
                month=today.strftime("%Y-%m"),
                total_income=income,
                period_start_day=1,
            )
        )
        if spent_today:
            db_session.add(
                Expense(
                    telegram_id=1001,
                    amount=spent_today,
                    description="траты",
                    date=today,
                )
            )
        await db_session.commit()

        from src.bot.handlers.menu import _build_status

        return (await _build_status(1001))[0]

    async def test_free_is_346_not_zero(self, db_session, monkeypatch):
        text = await self._status(
            db_session,
            monkeypatch,
            today=datetime(2026, 9, 14),
            income=159149,
            spent_today=9015,
        )
        assert "Свободно 346 ₽" in text
        assert "Потрачено 9,015 ₽" in text
        assert "Остаток 150,134 ₽" in text
        assert "Лимит на завтра 9,383 ₽/день" in text
        assert "План на сегодня" not in text
        assert "Перерасход 0 ₽" not in text

    async def test_plan_9045_free_5376(self, db_session, monkeypatch):
        text = await self._status(
            db_session,
            monkeypatch,
            today=datetime(2026, 9, 13),
            income=162818,
            spent_today=3669,
        )
        assert "Свободно 5,376 ₽" in text
        assert "Лимит на завтра 9,361 ₽/день" in text
        assert "План на сегодня" not in text

    async def test_overrun_shown_with_number_and_warning(self, db_session, monkeypatch):
        text = await self._status(
            db_session,
            monkeypatch,
            today=datetime(2026, 9, 14),
            income=159137,
            spent_today=18343,
        )
        assert "Свободно 0 ₽" in text
        assert "Перерасход 8,982 ₽" in text
        assert "Потрачено 18,343 ₽ ⚠️" in text
        assert "План на сегодня" not in text
        # перерасход не меняет зону: план 9 361 при базе 5 305 — это «В норме»
        assert phrases.STATUS_ZONE_NORM in text

    async def test_period_end_label_uses_end_day(self, db_session, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 9, 17))
        db_session.add(User(telegram_id=1001))
        db_session.add(
            Budget(
                telegram_id=1001,
                month="2026-08",
                total_income=100000,
                period_start_day=20,
            )
        )
        await db_session.commit()

        from src.bot.handlers.menu import _build_status

        text, _ = await _build_status(1001)
        assert "до 19-го" in text
        assert "до 20-го" not in text


class TestPlanInvariant:
    def test_exhausted_budget_does_not_grow_plan(self):
        # период уже перерасходован: raw отрицательный
        raw = -5000
        plan = get_plan_today(raw, 3000, 10)
        assert plan == 0
        assert get_overrun_today(plan, 3000) == 3000

        plan_later = get_plan_today(raw, 9000, 10)
        assert plan_later == pytest.approx(400)
        assert get_overrun_today(plan_later, 9000) == pytest.approx(8600)

    def test_last_day_overrun_is_detected_when_raw_negative(self):
        # в последний день план = весь остаток на утро; перерасход виден,
        # если остаток уже был отрицательным
        plan = get_plan_today(-1000, 500, 1)
        assert plan == 0
        assert get_overrun_today(plan, 500) == 500


class TestDaysRemainingEdge:
    @pytest.mark.parametrize(
        ("month", "start", "today", "expected"),
        [
            ("2026-01", 31, datetime(2026, 1, 31), 29),  # 31.01–28.02
            ("2026-01", 31, datetime(2026, 2, 28), 1),
            ("2026-01", 31, datetime(2026, 2, 27), 2),
        ],
    )
    def test_start_day_larger_than_february(self, monkeypatch, month, start, today, expected):
        _freeze(monkeypatch, today)
        budget = Budget(telegram_id=1, month=month, period_start_day=start)
        assert budget.days_remaining == expected

    def test_february_period_length_for_start_31(self):
        assert period_total_days("2026-01", 31) == 29
        # старт в феврале клампится на 28-е, следующий — 31 марта,
        # поэтому период 28.02–30.03 = 31 день
        assert period_total_days("2026-02", 31) == 31


class TestStatusInvariant:
    async def test_plan_stays_fixed_after_intraday_expense(self, db_session, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 9, 14))
        db_session.add(User(telegram_id=1001))
        db_session.add(
            Budget(
                telegram_id=1001,
                month="2026-09",
                total_income=159149,
                period_start_day=1,
            )
        )
        db_session.add(
            Expense(
                telegram_id=1001,
                amount=9015,
                description="траты",
                date=datetime(2026, 9, 14),
            )
        )
        await db_session.commit()

        from src.bot.handlers.menu import _build_status

        before, _ = await _build_status(1001)
        db_session.add(
            Expense(
                telegram_id=1001,
                amount=1000,
                description="ещё трата",
                date=datetime(2026, 9, 14),
            )
        )
        await db_session.commit()
        after, _ = await _build_status(1001)

        assert "Свободно 346 ₽" in before
        assert "Свободно 0 ₽" in after
        assert "План на сегодня" not in before
        assert "План на сегодня" not in after

    async def test_income_increase_recalculates_plan(self, db_session, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 9, 14))
        db_session.add(User(telegram_id=1001))
        budget = Budget(
            telegram_id=1001,
            month="2026-09",
            total_income=159149,
            period_start_day=1,
        )
        db_session.add(budget)
        await db_session.commit()

        from src.bot.handlers.menu import _build_status
        from src.services.budget_service import update_budget_field

        before, _ = await _build_status(1001)
        await update_budget_field(1001, "total_income", 169149)
        after, _ = await _build_status(1001)

        assert "Лимит на завтра 9,946 ₽/день" in before
        assert "Лимит на завтра 10,571 ₽/день" in after

    async def test_overrun_footer_is_not_green(self, db_session, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 9, 14))
        db_session.add(User(telegram_id=1001))
        db_session.add(
            Budget(
                telegram_id=1001,
                month="2026-09",
                total_income=159137,
                period_start_day=1,
            )
        )
        db_session.add(
            Expense(
                telegram_id=1001,
                amount=18343,
                description="траты",
                date=datetime(2026, 9, 14),
            )
        )
        await db_session.commit()

        from src.bot.handlers.menu import _build_status

        text, _ = await _build_status(1001)
        assert "Идём идеально" not in text
        assert phrases.STATUS_ZONE_NORM in text
        assert "Перерасход 8,982 ₽" in text
        assert (
            phrases.STATUS_FOOTER_RED_NO_NUM_1 in text or phrases.STATUS_FOOTER_RED_NO_NUM_2 in text
        )
