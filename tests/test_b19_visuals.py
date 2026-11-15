from datetime import datetime
from types import SimpleNamespace

from src.services.monthly_report import _zone_for_period, format_summary_text
from src.utils import phrases

ZONE_EMOJI = ("🟢", "🔵", "🟡", "🔴", "⚪", "⛔")


def _data() -> dict:
    return {
        "budget": SimpleNamespace(
            total_income=100000.0,
            daily_limit=3000.0,
            mandatory_payments=0.0,
        ),
        "active": False,
        "period_start": datetime(2026, 9, 1),
        "period_end": datetime(2026, 9, 30, 23, 59, 59),
        "breakdown": [("🍔 Еда", 3, 50000.0)],
        "total_spent": 50000.0,
        "avg_day": 0.0,
        "zone_label": phrases.MONTHLY_ZONE_GREEN,
        "top_cat_name": "🍔 Еда",
        "totem_name": "Винни-Пух",
        "totem_phrase": "—",
        "totem_emoji": "🍯",
        "wishlist_current": 0.0,
        "wishlist_target": 0.0,
        "bdf_amount": 0.0,
        "bdf_used": 0.0,
        "rounding_total": 0.0,
        "period_label": "1 сен – 30 сен 2026",
    }


def test_status_zero_has_no_cross():
    assert phrases.STATUS_REMAINING_ZERO == "Свободно 0 ₽"


def test_period_zone_returns_label_without_emoji():
    label = _zone_for_period(50000.0, 100000.0, 0.0, 0.0)

    assert label == phrases.MONTHLY_ZONE_GREEN
    for emoji in ZONE_EMOJI:
        assert emoji not in label


def test_monthly_report_zone_line_has_no_emoji():
    text = format_summary_text(_data())

    assert f"Зона: {phrases.MONTHLY_ZONE_GREEN}" in text
    for emoji in ZONE_EMOJI:
        assert emoji not in text
