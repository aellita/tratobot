from datetime import datetime
from types import SimpleNamespace

from src.services.monthly_report import format_summary_text
from src.utils import phrases


def _data(*, total_spent: float, active: bool = False) -> dict:
    return {
        "budget": SimpleNamespace(
            total_income=100000.0,
            daily_limit=3000.0,
            mandatory_payments=10000.0,
        ),
        "active": active,
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


class TestSavedAndOverrun:
    def test_finished_period_shows_saved(self):
        text = format_summary_text(_data(total_spent=80000.0))
        assert phrases.MONTHLY_SAVED.format(amount="20,000") in text

    def test_finished_period_shows_overrun(self):
        text = format_summary_text(_data(total_spent=120000.0))
        assert phrases.MONTHLY_OVERRUN.format(amount="20,000") in text

    def test_exact_zero_has_no_line(self):
        text = format_summary_text(_data(total_spent=100000.0))
        assert "Сэкономлено" not in text
        assert "Перерасход" not in text

    def test_active_period_has_no_saved_line(self):
        text = format_summary_text(_data(total_spent=80000.0, active=True))
        assert "Сэкономлено" not in text
        assert "Перерасход" not in text


class TestDetailsCleanup:
    def test_dead_details_are_gone(self):
        text = format_summary_text(_data(total_spent=80000.0))
        assert "Кубышка" not in text
        assert "Хотелка" not in text
        assert "Округления" not in text
        assert "округление" not in text

    def test_live_details_stay(self):
        text = format_summary_text(_data(total_spent=80000.0))
        assert "Финальный дневной лимит" in text
        assert "Обязательные платежи" in text
