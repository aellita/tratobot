from src.services.morning_report import _yesterday_line, _yesterday_plan


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
