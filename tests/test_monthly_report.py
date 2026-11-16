from datetime import datetime
from types import SimpleNamespace

from src.services.monthly_report import compute_avg_day, format_summary_text
from src.utils import phrases
from src.utils.helpers import period_dates, period_total_days


def _period(month: str, start_day: int) -> tuple[datetime, int]:
    period_start, _ = period_dates(month, start_day)
    return period_start, period_total_days(month, start_day)


class TestAvgDayClosedPeriod:
    def test_31_day_period(self):
        start, days = _period("2026-08", 20)
        avg = compute_avg_day(80000.0, start, days, False, datetime(2026, 9, 20))
        assert days == 31
        assert avg == 80000.0 / 31
        assert f"{avg:,.0f}" == "2,581"

    def test_28_day_february(self):
        start, days = _period("2026-02", 1)
        avg = compute_avg_day(80000.0, start, days, False, datetime(2026, 3, 1))
        assert days == 28
        assert avg == 80000.0 / 28
        assert f"{avg:,.0f}" == "2,857"

    def test_30_day_period(self):
        start, days = _period("2026-09", 1)
        avg = compute_avg_day(80000.0, start, days, False, datetime(2026, 10, 1))
        assert days == 30
        assert f"{avg:,.0f}" == "2,667"

    def test_closed_period_does_not_depend_on_today(self):
        start, days = _period("2026-08", 20)
        first = compute_avg_day(80000.0, start, days, False, datetime(2026, 9, 20))
        second = compute_avg_day(80000.0, start, days, False, datetime(2027, 1, 1))
        assert first == second


class TestAvgDayActivePeriod:
    def test_fifth_day_of_period(self):
        start, days = _period("2026-09", 1)
        avg = compute_avg_day(10000.0, start, days, True, datetime(2026, 9, 5))
        assert avg == 10000.0 / 5

    def test_offset_start_counts_from_period_start(self):
        start, days = _period("2026-08", 20)
        avg = compute_avg_day(17000.0, start, days, True, datetime(2026, 9, 5))
        assert days == 31
        assert avg == 17000.0 / 17

    def test_first_day_uses_one_day(self):
        start, days = _period("2026-09", 1)
        avg = compute_avg_day(1000.0, start, days, True, datetime(2026, 9, 1))
        assert avg == 1000.0

    def test_last_day_uses_full_period(self):
        start, days = _period("2026-09", 1)
        avg = compute_avg_day(30000.0, start, days, True, datetime(2026, 9, 30))
        assert avg == 30000.0 / 30

    def test_elapsed_days_are_capped_by_period_length(self):
        start, days = _period("2026-09", 1)
        avg = compute_avg_day(30000.0, start, days, True, datetime(2026, 10, 5))
        assert avg == 30000.0 / 30

    def test_zero_spent(self):
        start, days = _period("2026-09", 1)
        assert compute_avg_day(0.0, start, days, True, datetime(2026, 9, 5)) == 0.0


def _summary_data(total_spent: float = 80000.0) -> dict:
    return {
        "budget": SimpleNamespace(
            total_income=100000.0,
            daily_limit=3000.0,
            mandatory_payments=10000.0,
        ),
        "active": False,
        "period_start": datetime(2026, 9, 1),
        "period_end": datetime(2026, 9, 30, 23, 59, 59),
        "breakdown": [],
        "total_spent": total_spent,
        "avg_day": 0.0,
        "zone_label": phrases.MONTHLY_ZONE_GREEN,
        "top_cat_name": "—",
        "totem_name": "Чебурашка",
        "totem_phrase": "—",
        "totem_emoji": "🍊",
        "period_label": "1 сен – 30 сен 2026",
    }


class TestDetailsSuffix:
    def test_last_code_tag_stays_closed(self):
        text = format_summary_text(_summary_data())
        assert "</code>\n</details>" in text
        assert "</code\n" not in text

    def test_details_end_with_mandatory_line(self):
        text = format_summary_text(_summary_data())
        assert text.endswith("Обязательные платежи: <code>10,000 ₽</code>\n</details>")
