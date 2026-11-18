from src.services.morning_report import _select_morning_zone, _yesterday_line, _yesterday_plan


def test_yesterday_plan_restores_what_user_saw():
    # Остаток сейчас 3504, вчера потрачено 7400, сегодня ещё ничего, до конца 3 дня.
    # Вчера утром было (3504 + 7400 + 0) / 4 = 2726 ₽/день.
    assert _yesterday_plan(3504.0, 7400.0, 0.0, 3) == 2726.0


def test_yesterday_plan_counts_todays_spending_back():
    # Остаток 7500 уже после сегодняшних 500: на начало вчера было
    # 7500 + 2000 + 500 = 10000, дней было 4 → 2500 ₽/день.
    assert _yesterday_plan(7500.0, 2000.0, 500.0, 3) == 2500.0


def test_yesterday_plan_is_not_the_base_limit():
    # Базовый лимит периода (доход / дни) в строке «Вчера» не участвует.
    assert _yesterday_plan(3504.0, 7400.0, 0.0, 3) != 6666.0


def test_yesterday_plan_is_zero_when_period_overspent():
    assert _yesterday_plan(-5000.0, 0.0, 0.0, 3) == 0.0


def test_yesterday_plan_with_zero_days_left_is_defensive():
    assert _yesterday_plan(1500.0, 800.0, 0.0, 0) == 2300.0


def test_yesterday_line_does_not_show_zero_overrun():
    # Разница меньше рубля: показываем «уложился», а не «перебор 0 ₽».
    line, ok = _yesterday_line(1000.9, 1000.1)

    assert ok is True
    assert "перебор" not in line


def test_yesterday_line_shows_real_overrun():
    line, ok = _yesterday_line(7400.0, 2726.0)

    assert ok is False
    assert "перебор 4674" in line


class TestB23EndOfPeriodPhrases:
    """B23: тон последних 3 дней — END_OK / END_YESTERDAY_OVERRUN / END_PLAN_SAGGED"""

    def test_end_ok_when_yesterday_ok_and_plan_ge_70pct(self):
        """END_OK: вчера уложился И план >= 70% базы."""
        zone = _select_morning_zone(
            end_of_period=True,
            money_for_life=10000.0,
            free_today=1000.0,
            overrun_today=0.0,
            plan_today=7500.0,  # 75% от базы 10000
            base_daily_limit=10000.0,
            yesterday_ok=True,
        )
        assert zone == "END_OK"

    def test_end_ok_boundary_70pct_exact(self):
        """END_OK: граница 70% точная (float precision safe)."""
        plan_today = 10000.0 * 0.7  # 7000.0
        zone = _select_morning_zone(
            end_of_period=True,
            money_for_life=10000.0,
            free_today=1000.0,
            overrun_today=0.0,
            plan_today=plan_today,
            base_daily_limit=10000.0,
            yesterday_ok=True,
        )
        assert zone == "END_OK"

    def test_end_plan_sagged_when_plan_rounds_below_70pct(self):
        """END_PLAN_SAGGED: план округляется к значению < 70% (6999 → 6999)."""
        # 6999.4 округляется к 6999, что < 70% от 10000
        zone = _select_morning_zone(
            end_of_period=True,
            money_for_life=10000.0,
            free_today=1000.0,
            overrun_today=0.0,
            plan_today=6999.4,  # round(6999.4) = 6999 < 7000
            base_daily_limit=10000.0,
            yesterday_ok=True,
        )
        assert zone == "END_PLAN_SAGGED"

    def test_end_ok_when_plan_rounds_to_70pct(self):
        """END_OK: план округляется ровно к 70% (6999.6 → 7000)."""
        zone = _select_morning_zone(
            end_of_period=True,
            money_for_life=10000.0,
            free_today=1000.0,
            overrun_today=0.0,
            plan_today=6999.6,  # round(6999.6) = 7000 >= 7000
            base_daily_limit=10000.0,
            yesterday_ok=True,
        )
        assert zone == "END_OK"

    def test_end_yesterday_overrun_when_yesterday_not_ok(self):
        """END_YESTERDAY_OVERRUN: вчера был перебор."""
        zone = _select_morning_zone(
            end_of_period=True,
            money_for_life=10000.0,
            free_today=1000.0,
            overrun_today=0.0,
            plan_today=8000.0,
            base_daily_limit=10000.0,
            yesterday_ok=False,
        )
        assert zone == "END_YESTERDAY_OVERRUN"

    def test_end_plan_sagged_when_yesterday_ok_but_plan_lt_70pct(self):
        """END_PLAN_SAGGED: вчера уложился, но план < 70% базы."""
        zone = _select_morning_zone(
            end_of_period=True,
            money_for_life=10000.0,
            free_today=1000.0,
            overrun_today=0.0,
            plan_today=6000.0,  # 60% от базы
            base_daily_limit=10000.0,
            yesterday_ok=True,
        )
        assert zone == "END_PLAN_SAGGED"

    def test_end_plan_sagged_when_base_zero(self):
        """END_PLAN_SAGGED: базовый лимит 0 (нельзя быть >= 70%)."""
        zone = _select_morning_zone(
            end_of_period=True,
            money_for_life=5000.0,
            free_today=1000.0,
            overrun_today=0.0,
            plan_today=1000.0,
            base_daily_limit=0.0,
            yesterday_ok=True,
        )
        assert zone == "END_PLAN_SAGGED"

    def test_end_empty_when_money_for_life_zero(self):
        """END_EMPTY: денег нет (money_for_life <= 0)."""
        zone = _select_morning_zone(
            end_of_period=True,
            money_for_life=0.0,
            free_today=0.0,
            overrun_today=0.0,
            plan_today=1000.0,
            base_daily_limit=10000.0,
            yesterday_ok=True,
        )
        assert zone == "END_EMPTY"

    def test_end_over_when_overrun_today(self):
        """END_OVER: перебор сегодня (приоритет над вчерашним)."""
        zone = _select_morning_zone(
            end_of_period=True,
            money_for_life=5000.0,
            free_today=-500.0,
            overrun_today=500.0,
            plan_today=8000.0,
            base_daily_limit=10000.0,
            yesterday_ok=True,
        )
        assert zone == "END_OVER"
