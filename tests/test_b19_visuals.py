from datetime import datetime
from types import SimpleNamespace

from src.services.monthly_report import compute_saved_state, format_summary_text
from src.utils import phrases

ZONE_EMOJI = ("🟢", "🔵", "🟡", "🔴", "⚪", "⛔")


def _data() -> dict:
    available = 100000.0
    saved, tier = compute_saved_state(available, 50000.0)
    return {
        "budget": SimpleNamespace(
            total_income=100000.0,
            daily_limit=3000.0,
            mandatory_payments=0.0,
            black_day_fund=0.0,
            period_start_day=1,
        ),
        "active": False,
        "period_start": datetime(2026, 9, 1),
        "period_end": datetime(2026, 9, 30, 23, 59, 59),
        "breakdown": [("🍔 Еда", 3, 50000.0)],
        "total_spent": 50000.0,
        "avg_day": 0.0,
        "income": 100000.0,
        "added_income": 0.0,
        "available": available,
        "saved": saved,
        "saved_tier": tier,
        "top_cat_name": "🍔 Еда",
        "totem_name": "Винни-Пух",
        "totem_phrase": "—",
        "totem_emoji": "🍯",
        "period_label": "1 сен – 30 сен 2026",
    }


def test_status_zero_has_no_cross():
    assert phrases.STATUS_REMAINING_ZERO == "Свободно 0 ₽"


def test_monthly_report_has_no_zone_line():
    text = format_summary_text(_data())

    assert "Зона:" not in text
    for emoji in ZONE_EMOJI:
        assert emoji not in text


def test_monthly_report_shows_saved_phrase():
    text = format_summary_text(_data())

    assert phrases.MONTHLY_SAVED_GREEN.format(amount="50,000") in text
