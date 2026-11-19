from datetime import datetime

import pytest

from src.db.models.models import Budget, Expense, User
from src.services.morning_report import _select_morning_zone
from src.services.status_zones import (
    TREND_DEAD,
    TREND_GREEN,
    TREND_LIGHT,
    TREND_NONE,
    TREND_OVER,
    TREND_SQUEEZE,
    ZONE_ATAS,
    ZONE_BLUE,
    ZONE_FINISH,
    ZONE_GREEN,
    ZONE_RED,
    ZONE_YELLOW,
    forecast_amount,
    limit_pressure_pct,
    limit_trend,
    plan_zone,
    status_zone,
    tomorrow_plan,
)
from src.utils import phrases


def _freeze(monkeypatch, dt: datetime):
    monkeypatch.setattr("src.db.models.models._msk_now", lambda: dt)
    monkeypatch.setattr("src.bot.handlers.menu.get_msk_now", lambda: dt)
    monkeypatch.setattr("src.services.budget_service.get_msk_now", lambda: dt)
    monkeypatch.setattr("src.services.expense_service.get_msk_now", lambda: dt)
    monkeypatch.setattr("src.utils.helpers.get_msk_now", lambda: dt)


class TestPlanZone:
    @pytest.mark.parametrize(
        ("plan", "expected"),
        [
            (1000, ZONE_GREEN),
            (900, ZONE_GREEN),
            (899, ZONE_BLUE),
            (700, ZONE_BLUE),
            (699, ZONE_YELLOW),
            (260, ZONE_YELLOW),
            (259, ZONE_RED),
            (0, ZONE_RED),
        ],
    )
    def test_thresholds_90_70_26(self, plan, expected):
        assert plan_zone(plan, 1000) == expected

    def test_zero_base_is_red(self):
        assert limit_pressure_pct(500, 0) == 0
        assert plan_zone(500, 0) == ZONE_RED

    def test_plan_zone_ignores_day_state(self):
        # зона считается только от plan/base
        assert plan_zone(950, 1000) == ZONE_GREEN
        assert plan_zone(800, 1000) == ZONE_BLUE
        assert plan_zone(500, 1000) == ZONE_YELLOW
        assert plan_zone(200, 1000) == ZONE_RED


class TestStatusZone:
    def test_overrun_and_zero_free_do_not_change_zone(self):
        # free/overrun сюда даже не передаются — зона только от плана
        assert (
            status_zone(plan_today=950, base_daily_limit=1000, money_for_life=100, days_left=10)
            == ZONE_GREEN
        )

    def test_end_of_period_is_finish_when_money_left(self):
        assert (
            status_zone(plan_today=0, base_daily_limit=1000, money_for_life=100, days_left=3)
            == ZONE_FINISH
        )

    def test_end_of_period_is_atas_when_money_gone(self):
        assert (
            status_zone(plan_today=0, base_daily_limit=1000, money_for_life=0, days_left=2)
            == ZONE_ATAS
        )


class TestTomorrowPlan:
    def test_divides_by_days_without_today(self):
        assert tomorrow_plan(159149, 18) == pytest.approx(159149 / 17)

    def test_last_day_has_no_tomorrow(self):
        assert tomorrow_plan(5000, 1) == 0

    def test_forecast_only_when_plan_shrinks(self):
        assert forecast_amount(9000, 8000, 10) == 8000
        assert forecast_amount(9000, 9000, 10) is None
        assert forecast_amount(9000, 9500, 10) is None

    def test_no_forecast_in_last_three_days(self):
        assert forecast_amount(9000, 100, 3) is None
        assert forecast_amount(9000, 100, 1) is None


class TestLimitTrend:
    @pytest.mark.parametrize(
        ("plan", "expected"),
        [
            (1000, TREND_GREEN),
            (900, TREND_GREEN),
            (899, TREND_LIGHT),
            (700, TREND_LIGHT),
            (699, TREND_SQUEEZE),
            (260, TREND_SQUEEZE),
            (259, TREND_DEAD),
        ],
    )
    def test_tiers(self, plan, expected):
        assert limit_trend(plan, 1000, free_today=1, overrun_today=0) == expected

    def test_overrun_forces_red_even_with_high_plan(self):
        assert limit_trend(5000, 1000, free_today=0, overrun_today=1) == TREND_OVER

    def test_zero_free_is_none(self):
        assert limit_trend(5000, 1000, free_today=0, overrun_today=0) == TREND_NONE

    def test_zero_base(self):
        assert limit_pressure_pct(500, 0) == 0


class TestForecastRounding:
    def test_equal_after_rounding_is_not_a_forecast(self):
        assert forecast_amount(1000.4, 1000.3, 10) is None

    def test_real_shrink_is_a_forecast(self):
        assert forecast_amount(1000.4, 900.2, 10) == 900


class TestMorningTone:
    def test_yesterday_ok_does_not_say_brake(self):
        zone = _select_morning_zone(
            end_of_period=False,
            money_for_life=10000,
            free_today=100,
            overrun_today=0,
            plan_today=800,
            base_daily_limit=1000,
            yesterday_ok=True,
        )
        assert zone == "YELLOW_LIGHT_OK"

    def test_yesterday_over_keeps_light_warning(self):
        zone = _select_morning_zone(
            end_of_period=False,
            money_for_life=10000,
            free_today=100,
            overrun_today=0,
            plan_today=800,
            base_daily_limit=1000,
            yesterday_ok=False,
        )
        assert zone == "YELLOW_LIGHT"

    def test_grown_limit_is_not_nervous(self):
        zone = _select_morning_zone(
            end_of_period=False,
            money_for_life=10000,
            free_today=100,
            overrun_today=0,
            plan_today=1200,
            base_daily_limit=1000,
            yesterday_ok=True,
        )
        assert zone == "GREEN"

    def test_overrun_beats_green(self):
        zone = _select_morning_zone(
            end_of_period=False,
            money_for_life=10000,
            free_today=0,
            overrun_today=500,
            plan_today=1200,
            base_daily_limit=1000,
            yesterday_ok=True,
        )
        assert zone == "OVER"

    def test_yesterday_over_blocks_praise(self):
        zone = _select_morning_zone(
            end_of_period=False,
            money_for_life=10000,
            free_today=100,
            overrun_today=0,
            plan_today=1200,
            base_daily_limit=1000,
            yesterday_ok=False,
        )
        assert zone == "OVER_YESTERDAY"


class TestStatusFooter:
    def test_compression_shows_tomorrow_number(self):
        from src.bot.handlers.menu import _pick_status_footer

        footer, has_number = _pick_status_footer(
            end_of_period=False,
            money_for_life=9000,
            overrun_today=0,
            free_today=100,
            plan_today=1000,
            plan_tomorrow=800,
            days_left=10,
            base_daily_limit=1000,
        )
        assert "800" in footer
        assert has_number is True

    def test_no_compression_has_no_numbers(self):
        from src.bot.handlers.menu import _pick_status_footer

        footer, has_number = _pick_status_footer(
            end_of_period=False,
            money_for_life=9000,
            overrun_today=0,
            free_today=100,
            plan_today=800,
            plan_tomorrow=1000,
            days_left=10,
            base_daily_limit=1000,
        )
        assert "₽" not in footer
        assert "1000" not in footer
        assert has_number is False

    def test_final_days_have_no_forecast(self):
        from src.bot.handlers.menu import _pick_status_footer

        footer, has_number = _pick_status_footer(
            end_of_period=True,
            money_for_life=9000,
            overrun_today=0,
            free_today=100,
            plan_today=1000,
            plan_tomorrow=100,
            days_left=3,
            base_daily_limit=1000,
        )
        assert "₽" not in footer
        assert "сожмётся" not in footer
        assert has_number is False

    def test_overrun_footer_is_not_relaxed_and_has_no_number(self):
        from src.bot.handlers.menu import _pick_status_footer

        footer, has_number = _pick_status_footer(
            end_of_period=False,
            money_for_life=9000,
            overrun_today=500,
            free_today=0,
            plan_today=1000,
            plan_tomorrow=800,
            days_left=10,
            base_daily_limit=1000,
        )
        assert "полегче" not in footer.lower()
        assert phrases.STATUS_FOOTER_GREEN_2 not in footer
        assert "₽" not in footer
        assert has_number is False

    def test_squeezed_plan_still_has_money_today(self):
        from src.bot.handlers.menu import _pick_status_footer

        footer, has_number = _pick_status_footer(
            end_of_period=False,
            money_for_life=9000,
            overrun_today=0,
            free_today=800,
            plan_today=600,
            plan_tomorrow=1000,
            days_left=10,
            base_daily_limit=1000,
        )
        assert phrases.STATUS_FOOTER_YELLOW_NONE_NO_NUM not in footer
        assert "Свободного лимита нет" not in footer
        assert has_number is False

    def test_final_days_without_money_today_are_not_a_victory(self):
        from src.bot.handlers.menu import _pick_status_footer

        footer, _ = _pick_status_footer(
            end_of_period=True,
            money_for_life=9000,
            overrun_today=0,
            free_today=0,
            plan_today=1000,
            plan_tomorrow=100,
            days_left=3,
            base_daily_limit=1000,
        )
        assert phrases.STATUS_FOOTER_END_OK_1 not in footer
        assert phrases.STATUS_FOOTER_END_OK_2 not in footer
        assert phrases.STATUS_FOOTER_END_OK_3 not in footer
        assert phrases.STATUS_FOOTER_END_TIGHT_1 in footer or (
            phrases.STATUS_FOOTER_END_TIGHT_2 in footer
        )

    def test_no_money_uses_dead_phrase(self):
        from src.bot.handlers.menu import _pick_status_footer

        footer, has_number = _pick_status_footer(
            end_of_period=False,
            money_for_life=0,
            overrun_today=0,
            free_today=0,
            plan_today=0,
            plan_tomorrow=0,
            days_left=10,
            base_daily_limit=1000,
        )
        assert footer in {
            phrases.STATUS_FOOTER_RED_DEAD_1,
            phrases.STATUS_FOOTER_RED_DEAD_2,
            phrases.STATUS_FOOTER_RED_DEAD_3,
        }
        assert has_number is False


class TestBaseDailyLimit:
    async def test_uses_stored_base_not_card_balance(self, db_session):
        from src.services.budget_service import get_base_daily_limit

        db_session.add(
            Budget(
                telegram_id=1001,
                month="2026-09",
                total_income=100000,
                mandatory_payments=0,
                black_day_fund=0,
                period_start_day=1,
                base_daily_limit=3333.0,
                free_money=5000,
            )
        )
        await db_session.commit()

        budget = await db_session.get(Budget, 1)
        assert await get_base_daily_limit(budget) == 3333.0
        # budget.daily_limit при free_money > 0 считается от остатка на карте
        assert budget.daily_limit != 3333.0

    async def test_falls_back_to_income_formula(self, db_session):
        from src.services.budget_service import get_base_daily_limit

        db_session.add(
            Budget(
                telegram_id=1002,
                month="2026-09",
                total_income=100000,
                mandatory_payments=10000,
                black_day_fund=5000,
                period_start_day=1,
            )
        )
        await db_session.commit()

        from sqlalchemy import select

        budget = (
            await db_session.execute(select(Budget).where(Budget.telegram_id == 1002))
        ).scalar_one()
        base = await get_base_daily_limit(budget)
        assert base == pytest.approx(85000 / 30)


class TestStatusRendering:
    @staticmethod
    async def _seed(
        db_session,
        income: float,
        spent_period: float,
        spent_today: float,
        today: datetime = datetime(2026, 9, 14),
    ):
        db_session.add(User(telegram_id=1001))
        db_session.add(
            Budget(
                telegram_id=1001,
                month="2026-09",
                total_income=income,
                period_start_day=1,
            )
        )
        if spent_period:
            db_session.add(
                Expense(
                    telegram_id=1001,
                    amount=spent_period,
                    description="период",
                    date=datetime(2026, 9, 5),
                )
            )
        if spent_today:
            db_session.add(
                Expense(
                    telegram_id=1001,
                    amount=spent_today,
                    description="сегодня",
                    date=today,
                )
            )
        await db_session.commit()

    async def test_zone_uses_plan_share(self, db_session, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 9, 14))
        # 80% периода потрачено: остаток 20 000 на 17 дней = 1 176,
        # база 3 333 → 35% → жёлтая зона
        await self._seed(db_session, income=100000, spent_period=80000, spent_today=0)

        from src.bot.handlers.menu import _build_status

        text, _ = await _build_status(1001)
        assert phrases.STATUS_ZONE_LOW in text
        assert phrases.STATUS_ZONE_NORM not in text

    async def test_zero_free_does_not_demote_zone(self, db_session, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 9, 15))
        # 62.5% периода потрачено: план 2 500, потрачено ровно 2 500,
        # база 3 333 → 75% → синяя зона, хотя свободно 0
        await self._seed(
            db_session,
            income=100000,
            spent_period=60000,
            spent_today=2500,
            today=datetime(2026, 9, 15),
        )

        from src.bot.handlers.menu import _build_status

        text, _ = await _build_status(1001)
        assert phrases.STATUS_REMAINING_ZERO in text
        assert phrases.STATUS_ZONE_SLIGHTLY_LOW in text
        assert phrases.STATUS_ZONE_NORM not in text
        assert phrases.STATUS_FOOTER_GREEN_2 not in text
        assert phrases.STATUS_FOOTER_GREEN_3 not in text
        assert phrases.STATUS_FOOTER_YELLOW_NONE_NO_NUM in text

    async def test_overrun_keeps_zone_and_red_footer(self, db_session, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 9, 14))
        await self._seed(db_session, income=100000, spent_period=5000, spent_today=20000)

        from src.bot.handlers.menu import _build_status

        text, _ = await _build_status(1001)
        assert phrases.STATUS_ZONE_NORM in text
        assert phrases.STATUS_ZONE_ZERO not in text
        assert "Полегче" not in text
        assert "полегче" not in text
        assert phrases.STATUS_FOOTER_GREEN_2 not in text
        assert "⚠️" in text
        # Сумма перерасхода видна рядом с «Свободно 0 ₽» и «⚠️».
        assert "Перерасход 14,411 ₽" in text

    async def test_last_three_days_use_final_phrases_without_forecast(
        self, db_session, monkeypatch
    ):
        _freeze(monkeypatch, datetime(2026, 9, 28))
        await self._seed(db_session, income=100000, spent_period=99000, spent_today=0)

        from src.bot.handlers.menu import _build_status

        text, _ = await _build_status(1001)
        assert phrases.STATUS_ZONE_FINISH in text
        assert any(
            phrase in text
            for phrase in (
                phrases.STATUS_FOOTER_END_OK_1,
                phrases.STATUS_FOOTER_END_OK_2,
                phrases.STATUS_FOOTER_END_OK_3,
                phrases.STATUS_FOOTER_END_OVER_1,
                phrases.STATUS_FOOTER_END_OVER_2,
            )
        )
        assert "сожмётся" not in text

    async def test_period_shows_tomorrow_limit_when_footer_has_no_number(
        self, db_session, monkeypatch
    ):
        _freeze(monkeypatch, datetime(2026, 9, 14))
        await self._seed(db_session, income=159149, spent_period=0, spent_today=9015)

        from src.bot.handlers.menu import _build_status

        text, _ = await _build_status(1001)
        # остаток 150 134, дней 17 → на завтра 150 134 / 16 = 9 383
        assert phrases.STATUS_TOMORROW_LIMIT.format(amount="9,383") in text

    async def test_period_does_not_duplicate_number_from_footer(self, db_session, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 9, 14))
        # план 9 362, остаток 150 134 / 16 = 9 383 — завтра выше, футер без цифры.
        # Чтобы получить футер с цифрой, тратим так, чтобы завтра было ниже плана.
        await self._seed(db_session, income=159149, spent_period=0, spent_today=20000)

        from src.bot.handlers.menu import _build_status

        text, _ = await _build_status(1001)
        footer = text.rsplit("\n\n", 1)[-1]
        if "₽" in footer:
            assert phrases.STATUS_TOMORROW_LIMIT.format(amount="") not in text
