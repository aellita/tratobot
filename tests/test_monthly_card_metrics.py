from datetime import date, timedelta

from src.services.monthly_chart import (
    MonthlyCardInput,
    _x_label_indices,
    compute_card_metrics,
)


def _make_input(
    spent: list[float],
    *,
    start: date = date(2026, 11, 2),
    base: float = 5000.0,
    limits: list[float] | None = None,
    as_of: date | None = None,
    active: bool = True,
    upcoming: bool = False,
    expenses: list[dict] | None = None,
    total_spent: float | None = None,
    current_limit: float | None = None,
    available_income: float = 150000.0,
    period_end: date | None = None,
) -> MonthlyCardInput:
    days = len(spent)
    end = period_end or start + timedelta(days=max(days - 1, 0))
    if as_of is None:
        as_of = start + timedelta(days=days - 1) if active else end
    expenses = expenses or []
    return MonthlyCardInput(
        period_start=start,
        period_end=end,
        period_start_day=1,
        daily_spent=spent,
        daily_limit=base,
        total_spent=sum(spent) if total_spent is None else total_spent,
        expenses=expenses,
        expenses_count=len(expenses),
        as_of=as_of,
        is_active=active,
        upcoming=upcoming,
        daily_limits=limits if limits is not None else [base] * days,
        current_limit=current_limit if current_limit is not None else base,
        available_income=available_income,
    )


def _ids(metrics) -> list[str]:
    return [card.id for card in metrics.cards]


def test_upcoming_wide_card():
    metrics = compute_card_metrics(
        _make_input(
            [],
            start=date(2026, 12, 1),
            period_end=date(2026, 12, 31),
            as_of=date(2026, 11, 20),
            active=False,
            upcoming=True,
        )
    )

    assert metrics.state == "upcoming"
    assert metrics.cards == ()
    assert metrics.wide is not None
    assert metrics.wide.id == "upcoming"
    assert metrics.peak_callout is None


def test_quiet_active_is_gentle():
    metrics = compute_card_metrics(_make_input([0.0] * 5, active=True))

    assert metrics.state == "quiet"
    assert metrics.wide is not None
    assert metrics.wide.id == "quiet_mode"
    assert "кошелёк отдыхает" in metrics.wide.subtitle
    assert metrics.peak_callout is None


def test_quiet_closed_has_no_blame():
    metrics = compute_card_metrics(_make_input([0.0] * 5, active=False))

    assert metrics.wide is not None
    assert metrics.wide.id == "quiet_mode_closed"
    assert "ни одной траты" in metrics.wide.subtitle
    assert "не пользовался" not in metrics.wide.subtitle


def test_active_cards_include_streak_and_score():
    spent = [1000.0] * 8 + [6000.0] * 2 + [0.0] * 20

    metrics = compute_card_metrics(
        _make_input(spent, start=date(2026, 11, 2), as_of=date(2026, 11, 21))
    )

    assert metrics.tracked == 10
    assert metrics.green == 8
    assert metrics.green_pct == 80
    assert metrics.score == 85
    assert metrics.league == "Профи"
    assert _ids(metrics)[:2] == ["limit_streak", "bro_score"]
    assert metrics.cards[1].subtitle == "Профи · до Ниндзя 5 б."
    assert metrics.streak == 0
    assert metrics.best_streak == 8


def test_active_low_tracked_uses_forecast():
    metrics = compute_card_metrics(_make_input([1000.0, 1000.0, 0.0], as_of=date(2026, 11, 4)))

    assert metrics.score is None
    assert _ids(metrics)[:2] == ["limit_streak", "forecast"]
    assert metrics.cards[1].subtitle == "к концу периода"


def test_active_single_tracked_day_marks_forecast_as_rough():
    metrics = compute_card_metrics(_make_input([1000.0, 0.0], as_of=date(2026, 11, 3)))

    assert metrics.cards[1].id == "forecast"
    assert "очень грубо" in metrics.cards[1].subtitle
    assert metrics.cards[1].frog == "forecast_early"


def test_active_without_plan_uses_avg_and_top_expense():
    expenses = [
        {"date": "2026-11-02T12:00:00", "amount": 4000.0, "category": "Еда"},
        {"date": "2026-11-02T18:00:00", "amount": 1000.0, "category": "Еда"},
        {"date": "2026-11-03T12:00:00", "amount": 3000.0, "category": "Такси"},
    ]
    metrics = compute_card_metrics(
        _make_input(
            [5000.0, 3000.0, 0.0],
            base=0.0,
            as_of=date(2026, 11, 4),
            expenses=expenses,
        )
    )

    assert _ids(metrics)[:2] == ["avg_day", "top_expense"]
    assert metrics.cards[1].value == "4 000 ₽"
    assert metrics.cards[1].subtitle == "Еда"


def test_closed_cards_include_winrate_and_score():
    spent = [1000.0] * 20 + [6000.0] * 5 + [0.0] * 5

    metrics = compute_card_metrics(_make_input(spent, start=date(2026, 11, 2), active=False))

    assert metrics.tracked == 25
    assert metrics.green == 20
    assert metrics.green_pct == 80
    assert metrics.score == 85
    assert _ids(metrics)[:2] == ["limit_winrate", "bro_score"]
    assert metrics.cards[0].value == "20 из 25"
    assert metrics.budget_saved == 100000.0


def test_closed_low_tracked_uses_avg_day():
    metrics = compute_card_metrics(_make_input([1000.0, 1000.0, 0.0, 0.0], active=False))

    assert metrics.score is None
    assert _ids(metrics)[:2] == ["limit_winrate", "avg_day"]


def test_closed_without_plan_uses_avg_and_top_expense():
    expenses = [{"date": "2026-11-03T12:00:00", "amount": 2500.0, "category": "Дом"}]
    metrics = compute_card_metrics(
        _make_input([1000.0, 2500.0, 0.0], base=0.0, active=False, expenses=expenses)
    )

    assert _ids(metrics)[:2] == ["avg_day", "top_expense"]
    assert metrics.cards[1].value == "2 500 ₽"


def test_streak_ignores_zero_spend_days():
    spent = [1000.0, 0.0, 1000.0, 0.0, 1000.0, 0.0]

    metrics = compute_card_metrics(_make_input(spent, as_of=date(2026, 11, 7)))

    assert metrics.streak == 3
    assert metrics.tracked == 3
    assert metrics.green == 3


def test_streak_breaks_on_overrun():
    spent = [1000.0, 1000.0, 6000.0, 1000.0, 0.0]

    metrics = compute_card_metrics(_make_input(spent, as_of=date(2026, 11, 7)))

    assert metrics.streak == 1
    assert metrics.best_streak == 2
    assert "до лучшей 1 день" in metrics.cards[0].subtitle


def test_best_streak_excludes_current_run():
    spent = [1000.0, 1000.0, 6000.0, 1000.0, 1000.0, 0.0]

    metrics = compute_card_metrics(_make_input(spent, as_of=date(2026, 11, 8)))

    assert metrics.streak == 2
    assert metrics.best_streak == 2
    assert metrics.cards[0].subtitle == "повторяешь лучшую"


def test_green_uses_each_day_limit():
    metrics = compute_card_metrics(
        _make_input(
            [1000.0, 1500.0, 500.0, 0.0],
            limits=[1000.0, 1000.0, 1000.0, 1000.0],
            as_of=date(2026, 11, 6),
        )
    )

    assert metrics.tracked == 3
    assert metrics.green == 2
    assert metrics.score is not None


def test_score_gate_requires_three_tracked_days():
    metrics = compute_card_metrics(_make_input([1000.0, 1000.0, 0.0], as_of=date(2026, 11, 4)))

    assert metrics.tracked == 2
    assert metrics.score is None


def test_peak_callout_skips_today_and_has_no_category():
    spent = [1000.0, 2000.0, 4000.0, 0.0, 99999.0]

    metrics = compute_card_metrics(_make_input(spent, as_of=date(2026, 11, 6)))

    assert metrics.peak_callout == "4 ноя · 4 000 ₽"


def test_peak_callout_falls_back_to_today():
    metrics = compute_card_metrics(_make_input([99999.0, 0.0], as_of=date(2026, 11, 2)))

    assert metrics.peak_callout == "2 ноя · 99 999 ₽"


def test_peak_days_suppressed_for_single_day_period():
    metrics = compute_card_metrics(
        _make_input(
            [6000.0],
            start=date(2026, 11, 2),
            period_end=date(2026, 11, 2),
            active=False,
        )
    )

    assert "peak_days" not in _ids(metrics)
    assert metrics.cards[2].id == "top_category"


def test_peak_days_uses_minimal_top_two_days():
    spent = [10000.0, 10000.0, 10000.0] + [1000.0] * 4
    metrics = compute_card_metrics(
        _make_input(
            spent,
            start=date(2026, 11, 2),
            period_end=date(2026, 11, 8),
            active=False,
        )
    )

    assert metrics.cards[2].id == "peak_days"
    assert metrics.cards[2].value == "59%"
    assert metrics.cards[2].subtitle == "2 дня сделали кассу"


def test_peak_days_picks_one_day_when_one_is_enough():
    spent = [10000.0] + [1000.0] * 6
    metrics = compute_card_metrics(
        _make_input(
            spent,
            start=date(2026, 11, 2),
            period_end=date(2026, 11, 8),
            active=False,
        )
    )

    assert metrics.cards[2].id == "peak_days"
    assert metrics.cards[2].value == "62%"
    assert metrics.cards[2].subtitle == "1 день сделал кассу"


def test_peak_days_picks_three_days_when_needed():
    spent = [2000.0, 2000.0, 2000.0, 1500.0, 1500.0, 1500.0, 1500.0]
    metrics = compute_card_metrics(
        _make_input(
            spent,
            start=date(2026, 11, 2),
            period_end=date(2026, 11, 8),
            active=False,
        )
    )

    assert metrics.cards[2].id == "peak_days"
    assert metrics.cards[2].value == "50%"
    assert metrics.cards[2].subtitle == "3 дня сделали кассу"


def test_peak_days_requires_seven_tracked_days():
    spent = [3000.0, 3000.0, 3000.0, 1000.0, 1000.0, 1000.0]
    metrics = compute_card_metrics(
        _make_input(
            spent,
            start=date(2026, 11, 2),
            period_end=date(2026, 11, 7),
            active=False,
        )
    )

    assert "peak_days" not in _ids(metrics)
    assert metrics.cards[2].id == "top_category"


def test_peak_days_is_closed_period_only():
    spent = [3000.0, 3000.0, 3000.0, 1000.0, 1000.0, 1000.0, 1000.0, 0.0]
    metrics = compute_card_metrics(
        _make_input(
            spent,
            start=date(2026, 11, 2),
            as_of=date(2026, 11, 9),
            active=True,
        )
    )

    assert "peak_days" not in _ids(metrics)


def test_peak_days_requires_45_percent_of_spend():
    spent = [1800.0, 1800.0, 1800.0] + [1000.0] * 7
    metrics = compute_card_metrics(
        _make_input(
            spent,
            start=date(2026, 11, 2),
            period_end=date(2026, 11, 11),
            active=False,
        )
    )

    assert metrics.cards[2].id == "top_category"


def test_closed_without_plan_can_put_peak_days_in_slot_two():
    spent = [10000.0, 10000.0, 10000.0, 1000.0, 1000.0, 1000.0, 1000.0, 0.0]
    metrics = compute_card_metrics(
        _make_input(
            spent,
            start=date(2026, 11, 2),
            period_end=date(2026, 11, 9),
            base=0.0,
            active=False,
        )
    )

    assert metrics.cards[0].id == "avg_day"
    assert metrics.cards[1].id == "peak_days"
    assert "peak_days" not in _ids(metrics)[2:]


def test_weekend_tax_requires_weekday_and_weekend_days():
    spent = [1000.0, 1000.0]
    metrics = compute_card_metrics(
        _make_input(
            spent,
            start=date(2026, 11, 7),
            period_end=date(2026, 11, 8),
            active=False,
        )
    )

    assert "weekend_tax" not in _ids(metrics)
    assert metrics.cards[2].id == "top_category"


def test_weekend_tax_uses_40_percent_threshold():
    spent = [1000.0, 2000.0, 2000.0]
    metrics = compute_card_metrics(
        _make_input(
            spent,
            start=date(2026, 11, 6),
            period_end=date(2026, 11, 8),
            active=False,
        )
    )

    assert metrics.cards[2].id == "weekend_tax"
    assert metrics.cards[2].value == "80%"


def test_weekend_tax_is_not_shown_below_40_percent():
    spent = [3000.0, 500.0, 500.0]
    metrics = compute_card_metrics(
        _make_input(
            spent,
            start=date(2026, 11, 6),
            period_end=date(2026, 11, 8),
            active=False,
        )
    )

    assert "weekend_tax" not in _ids(metrics)
    assert metrics.cards[2].id == "top_category"


def test_night_food_uses_15_percent_threshold():
    expenses = [{"date": "2026-11-02T22:00:00", "amount": 500.0}]
    metrics = compute_card_metrics(
        _make_input(
            [1000.0, 1000.0, 1000.0],
            start=date(2026, 11, 2),
            period_end=date(2026, 11, 4),
            active=False,
            expenses=expenses,
        )
    )

    assert metrics.cards[2].id == "night_food"


def test_latte_effect_requires_five_checks_and_15_percent():
    expenses = [
        {"date": "2026-11-02T12:00:00", "amount": 200.0},
        {"date": "2026-11-03T12:00:00", "amount": 200.0},
        {"date": "2026-11-04T12:00:00", "amount": 200.0},
        {"date": "2026-11-05T12:00:00", "amount": 200.0},
        {"date": "2026-11-06T12:00:00", "amount": 200.0},
    ]
    metrics = compute_card_metrics(
        _make_input(
            [1000.0] * 5,
            start=date(2026, 11, 2),
            period_end=date(2026, 11, 6),
            active=False,
            expenses=expenses,
        )
    )

    assert metrics.cards[2].id == "latte_effect"


def test_latte_effect_needs_five_checks():
    expenses = [
        {"date": "2026-11-02T12:00:00", "amount": 250.0},
        {"date": "2026-11-03T12:00:00", "amount": 250.0},
        {"date": "2026-11-04T12:00:00", "amount": 250.0},
        {"date": "2026-11-05T12:00:00", "amount": 250.0},
    ]
    metrics = compute_card_metrics(
        _make_input(
            [1000.0] * 5,
            start=date(2026, 11, 2),
            period_end=date(2026, 11, 6),
            active=False,
            expenses=expenses,
        )
    )

    assert "latte_effect" not in _ids(metrics)
    assert metrics.cards[2].id == "top_category"


def test_top_category_is_fallback():
    expenses = [
        {"date": "2026-11-02T12:00:00", "amount": 3000.0, "category": "Еда"},
        {"date": "2026-11-02T13:00:00", "amount": 1000.0, "category": "Такси"},
    ]
    metrics = compute_card_metrics(
        _make_input(
            [4000.0, 0.0],
            start=date(2026, 11, 2),
            period_end=date(2026, 11, 3),
            active=False,
            expenses=expenses,
        )
    )

    assert metrics.cards[2].id == "top_category"
    assert metrics.cards[2].value == "Еда"
    assert metrics.cards[2].subtitle == "3 000 ₽ · 75%"


def test_tx_per_day_and_median_check():
    expenses = [
        {"date": "2026-11-02T12:00:00", "amount": 1000.0},
        {"date": "2026-11-02T13:00:00", "amount": 3000.0},
        {"date": "2026-11-02T14:00:00", "amount": 2000.0},
    ]
    metrics = compute_card_metrics(
        _make_input([6000.0, 0.0, 0.0, 0.0], as_of=date(2026, 11, 6), expenses=expenses)
    )

    tx_card = metrics.cards[3]
    assert tx_card.id == "tx_per_day"
    assert tx_card.value == "0,8"
    assert tx_card.subtitle == "медиана чека 2 000 ₽"


def test_pills_and_delta():
    metrics = compute_card_metrics(_make_input([1000.0] * 5, current_limit=6500.0))

    assert metrics.current_limit == 6500.0
    assert metrics.limit_delta == 1500.0
    assert metrics.green_pct == 100

    closed = compute_card_metrics(_make_input([1000.0] * 5, active=False, current_limit=6500.0))
    assert closed.current_limit == 5000.0
    assert closed.limit_delta is None
    assert closed.budget_saved == 145000.0


def test_weekend_tax_uses_completed_total_on_active_period():
    spent = [1000.0] * 5 + [2000.0, 2000.0, 50000.0]
    metrics = compute_card_metrics(
        _make_input(
            spent,
            start=date(2026, 11, 2),
            as_of=date(2026, 11, 9),
            active=True,
        )
    )

    assert metrics.cards[2].id == "weekend_tax"
    assert metrics.cards[2].value == "44%"


def test_x_axis_label_count_stays_at_most_six():
    for n in (1, 2, 5, 6, 10, 20, 30, 31):
        indices = _x_label_indices(n)
        assert indices[0] == 0
        assert indices[-1] == n - 1
        assert len(indices) <= 6


def test_no_duplicate_metric_ids_across_states():
    cases = [
        _make_input([1000.0] * 5),
        _make_input([6000.0] * 5),
        _make_input([1000.0, 0.0, 0.0]),
        _make_input([1000.0] * 5, base=0.0),
        _make_input([1000.0] * 5, active=False),
        _make_input([1000.0] * 5, base=0.0, active=False),
        _make_input([6000.0] * 5, active=False),
    ]

    for input_data in cases:
        ids = _ids(compute_card_metrics(input_data))
        assert len(ids) == 4
        assert len(set(ids)) == 4
