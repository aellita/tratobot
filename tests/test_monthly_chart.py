"""Tests for monthly_chart module."""

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.models.models import Budget
from src.services.monthly_chart import (
    CHART_WIDGET_HTML,
    MonthlyCardInput,
    _format_rus_month,
    _format_rus_period,
    _plural_ru,
    build_chart_data,
    build_chart_state,
    render_monthly_card_png,
    validate_widget_html,
)


def _make_input(**overrides) -> MonthlyCardInput:
    defaults = dict(
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        period_start_day=1,
        daily_spent=[100.0] * 30,
        daily_limit=5000.0,
        total_spent=3000.0,
        expenses=[],
        expenses_count=0,
        current_income=100000.0,
        prev_income=0.0,
    )
    defaults.update(overrides)
    return MonthlyCardInput(**defaults)


class TestBuildChartData:
    """Tests for build_chart_data function."""

    @pytest.fixture
    def sample_budget(self):
        return Budget(
            id=1,
            telegram_id=123,
            month="2026-11",
            total_income=100000,
            mandatory_payments=20000,
            black_day_fund=10000,
            period_start_day=1,
            free_money=0,
        )

    def _mock_session(self, rows):
        mock_result = MagicMock()
        mock_result.all.return_value = rows
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        return mock_session

    @pytest.mark.asyncio
    async def test_empty_period(self, sample_budget):
        """No expenses -> all zeros."""
        with patch("src.services.monthly_chart.async_session_maker") as mock_maker:
            mock_maker.return_value.__aenter__.return_value = self._mock_session([])
            with patch("src.services.monthly_chart.get_msk_now") as mock_now:
                mock_now.return_value = datetime(2026, 11, 20, 12, 0, 0)
                data = await build_chart_data(123, sample_budget)

        assert len(data) == 20  # Nov 1-20 (capped at today)
        assert all(d["spent"] == 0.0 for d in data)

    @pytest.mark.asyncio
    async def test_multiple_expenses_per_day(self, sample_budget):
        """Multiple expenses on same day should sum."""
        row_5 = MagicMock(expense_date=date(2026, 11, 5), total_spent=800.0)
        row_10 = MagicMock(expense_date=date(2026, 11, 10), total_spent=2000.0)

        with patch("src.services.monthly_chart.async_session_maker") as mock_maker:
            mock_maker.return_value.__aenter__.return_value = self._mock_session([row_5, row_10])
            with patch("src.services.monthly_chart.get_msk_now") as mock_now:
                mock_now.return_value = datetime(2026, 11, 20, 12, 0, 0)
                data = await build_chart_data(123, sample_budget)

        assert data[4]["spent"] == 800.0  # Nov 5
        assert data[9]["spent"] == 2000.0  # Nov 10

    @pytest.mark.asyncio
    async def test_full_past_period_is_not_capped(self, sample_budget):
        """A finished period must include every day, including the 31st."""
        row = MagicMock(expense_date=date(2026, 11, 30), total_spent=500.0)

        with patch("src.services.monthly_chart.async_session_maker") as mock_maker:
            mock_maker.return_value.__aenter__.return_value = self._mock_session([row])
            with patch("src.services.monthly_chart.get_msk_now") as mock_now:
                mock_now.return_value = datetime(2026, 12, 15, 12, 0, 0)
                data = await build_chart_data(123, sample_budget)

        assert len(data) == 30
        assert data[-1]["spent"] == 500.0

    @pytest.mark.asyncio
    async def test_future_period_is_empty(self, sample_budget):
        with patch("src.services.monthly_chart.async_session_maker") as mock_maker:
            mock_maker.return_value.__aenter__.return_value = self._mock_session([])
            with patch("src.services.monthly_chart.get_msk_now") as mock_now:
                mock_now.return_value = datetime(2026, 10, 15, 12, 0, 0)
                data = await build_chart_data(123, sample_budget)

        assert data == []


class TestBuildChartState:
    """Tests for build_chart_state function."""

    @pytest.fixture
    def budget(self):
        return Budget(
            id=1,
            telegram_id=123,
            month="2026-11",
            total_income=100000,
            mandatory_payments=0,
            black_day_fund=0,
            period_start_day=1,
            free_money=0,
        )

    def test_size_limit(self, budget):
        data = [{"spent": float(i * 100)} for i in range(31)]
        with patch("src.services.monthly_chart.get_msk_now") as mock_now:
            mock_now.return_value = datetime(2026, 11, 20, 12, 0, 0)
            state = build_chart_state(123, budget, data)

        json_str = __import__("json").dumps(state, separators=(",", ":"))
        assert len(json_str.encode("utf-8")) < 1024

    def test_compact_format(self, budget):
        data = [{"spent": 100.0}, {"spent": 200.0}]
        with patch("src.services.monthly_chart.get_msk_now") as mock_now:
            mock_now.return_value = datetime(2026, 11, 20, 12, 0, 0)
            state = build_chart_state(123, budget, data)

        assert set(state.keys()) == {"m", "s", "d", "lim", "a"}
        assert state["m"] == "2026-11"
        assert state["s"] == "2026-11-01"
        assert state["d"] == [100.0, 200.0]
        assert abs(state["lim"] - 3333.33) < 0.01
        assert state["a"] is True

    def test_frozen_limit_wins(self, budget):
        budget.base_daily_limit = 777.0
        with patch("src.services.monthly_chart.get_msk_now") as mock_now:
            mock_now.return_value = datetime(2026, 11, 20, 12, 0, 0)
            state = build_chart_state(123, budget, [{"spent": 1.0}])

        assert state["lim"] == 777.0

    def test_explicit_limit_wins(self, budget):
        budget.base_daily_limit = 777.0
        with patch("src.services.monthly_chart.get_msk_now") as mock_now:
            mock_now.return_value = datetime(2026, 11, 20, 12, 0, 0)
            state = build_chart_state(123, budget, [{"spent": 1.0}], daily_limit=123.0)

        assert state["lim"] == 123.0


class TestRenderMonthlyCardPng:
    """Tests for render_monthly_card_png function."""

    def test_png_validity(self):
        png_bytes = render_monthly_card_png(_make_input())
        assert len(png_bytes) > 1000
        assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    def test_png_dimensions(self):
        from io import BytesIO

        from PIL import Image

        png_bytes = render_monthly_card_png(_make_input())
        img = Image.open(BytesIO(png_bytes))
        assert img.size == (900, 840)

    def test_zero_spent_quiet_mode(self):
        png_bytes = render_monthly_card_png(_make_input(daily_spent=[0.0] * 30, total_spent=0.0))
        assert len(png_bytes) > 1000

    def test_non_empty_expenses_and_prev_period(self):
        expenses = [
            {"date": "2026-11-05T22:30:00", "amount": 500.0},
            {"date": "2026-11-06T10:00:00", "amount": 1500.0},
        ]
        prev_expenses = [
            {"date": "2026-10-05T22:30:00", "amount": 900.0},
        ]
        png_bytes = render_monthly_card_png(
            _make_input(
                expenses=expenses,
                expenses_count=len(expenses),
                prev_expenses=prev_expenses,
                prev_period_start=date(2026, 10, 1),
                prev_period_end=date(2026, 10, 31),
                prev_income=90000.0,
            )
        )
        assert len(png_bytes) > 1000

    def test_empty_daily_spent(self):
        png_bytes = render_monthly_card_png(_make_input(daily_spent=[], total_spent=0.0))
        assert len(png_bytes) > 1000

    def test_31_day_period(self):
        png_bytes = render_monthly_card_png(
            _make_input(daily_spent=[100.0] * 31, total_spent=3100.0)
        )
        assert len(png_bytes) > 1000

    def test_upcoming_period(self):
        png_bytes = render_monthly_card_png(
            _make_input(
                period_start=date(2026, 12, 1),
                period_end=date(2026, 12, 31),
                daily_spent=[],
                total_spent=0.0,
                expenses_count=0,
                as_of=date(2026, 11, 23),
                is_active=False,
                upcoming=True,
                daily_limits=[],
            )
        )
        assert len(png_bytes) > 1000

    def test_single_day_period(self):
        png_bytes = render_monthly_card_png(
            _make_input(
                period_start=date(2026, 11, 1),
                period_end=date(2026, 11, 1),
                daily_spent=[100.0],
                total_spent=100.0,
            )
        )
        assert len(png_bytes) > 1000

    def test_no_duplicate_metric_ids(self):
        test_cases = [
            {"daily_limit": 5000.0, "total_spent": 10000.0, "expenses_count": 10},
            {"daily_limit": 0.0, "total_spent": 5000.0, "expenses_count": 5},
            {"daily_limit": 5000.0, "total_spent": 0.0, "expenses_count": 0},
            {"daily_limit": 5000.0, "total_spent": 15000.0, "expenses_count": 20},
        ]
        for case in test_cases:
            png_bytes = render_monthly_card_png(_make_input(**case))
            assert len(png_bytes) > 1000


class TestChartWidgetHtml:
    """Tests for CHART_WIDGET_HTML."""

    def test_html_size(self):
        assert validate_widget_html()

    def test_html_contains_required_elements(self):
        assert "TelegramWidget" in CHART_WIDGET_HTML
        assert "chatDataChanged" in CHART_WIDGET_HTML
        assert "hapticFeedback" in CHART_WIDGET_HTML
        assert "selectionChanged" in CHART_WIDGET_HTML
        assert "--tg-theme-" in CHART_WIDGET_HTML
        assert "bar-over" in CHART_WIDGET_HTML
        assert "bar-ok" in CHART_WIDGET_HTML
        assert "limit-line" in CHART_WIDGET_HTML

    def test_tooltip_uses_local_dimensions(self):
        """showTooltip must not reference render()-local w/barH."""
        assert "svgW - 55" in CHART_WIDGET_HTML
        assert "barRect.height" in CHART_WIDGET_HTML


class TestFrogs:
    """Frogs are optional assets; missing files must never break the card."""

    def test_missing_asset_returns_none(self):
        from src.services.monthly_chart import _load_frog

        assert _load_frog("definitely_missing_frog") is None

    def test_specific_frogs_fall_back_to_generic(self):
        from src.services.monthly_chart import FROG_FALLBACKS

        assert FROG_FALLBACKS["bro_score_pro"] == "bro_score"
        assert FROG_FALLBACKS["limit_streak_record"] == "limit_streak"
        assert FROG_FALLBACKS["quiet_mode_closed"] == "quiet_mode"
        assert FROG_FALLBACKS["top_expense"] == "weekend_tax"
        assert FROG_FALLBACKS["tx_per_day"] == "avg_day"

    def test_fallback_targets_exist(self):
        from pathlib import Path

        from src.services.monthly_chart import FROG_FALLBACKS

        root = Path(__file__).resolve().parents[1] / "src" / "assets" / "frogs"
        names = {path.stem for path in root.glob("*.png")}
        assert set(FROG_FALLBACKS.values()) <= names

    def test_committed_frog_assets_are_png_rgba(self):
        from pathlib import Path

        from PIL import Image

        root = Path(__file__).resolve().parents[1] / "src" / "assets" / "frogs"
        names = {path.name for path in root.glob("*.png")}
        expected = {
            "avg_day.png",
            "bro_score.png",
            "bro_score_ninja.png",
            "bro_score_novice.png",
            "bro_score_own.png",
            "bro_score_pro.png",
            "forecast.png",
            "latte_effect.png",
            "limit_streak.png",
            "limit_streak_chasing.png",
            "limit_streak_first.png",
            "limit_streak_record.png",
            "limit_streak_repeat.png",
            "limit_streak_zero.png",
            "limit_winrate.png",
            "limit_winrate_clean.png",
            "limit_winrate_rough.png",
            "night_food.png",
            "peak_days.png",
            "quiet_mode.png",
            "top_category.png",
            "upcoming.png",
            "weekend_tax.png",
        }
        assert expected <= names
        for path in sorted(root.glob("*.png")):
            with Image.open(path) as img:
                assert img.format == "PNG"
                assert img.mode == "RGBA"
                assert img.size == (100, 100)


class TestFonts:
    """The PNG path must use the bundled Nunito, not Pillow's 10px default."""

    def test_nunito_font_loads(self):
        from src.services.monthly_chart import _load_font

        font = _load_font("bold", 26)
        assert font.size == 26
        assert font.getname()[0] == "Nunito"

    def test_cross_year_period(self):
        assert (
            _format_rus_period(date(2026, 12, 20), date(2027, 1, 19), 20)
            == "20 декабря 2026 — 19 января 2027"
        )


class TestRussianMonthNames:
    """Tests for Russian month name formatting."""

    def test_format_rus_month(self):
        assert _format_rus_month(date(2026, 1, 15)) == "января"
        assert _format_rus_month(date(2026, 2, 15)) == "февраля"
        assert _format_rus_month(date(2026, 12, 15)) == "декабря"

    def test_format_rus_period(self):
        assert _format_rus_period(date(2026, 1, 1), date(2026, 1, 31), 1) == "январь 2026"
        assert _format_rus_period(date(2026, 2, 1), date(2026, 2, 28), 1) == "февраль 2026"
        assert (
            _format_rus_period(date(2026, 11, 20), date(2026, 12, 19), 20)
            == "20 ноября — 19 декабря 2026"
        )
        assert (
            _format_rus_period(date(2026, 2, 20), date(2026, 3, 19), 20)
            == "20 февраля — 19 марта 2026"
        )


class TestPluralRu:
    """Tests for Russian pluralization."""

    def test_plural_ru(self):
        assert _plural_ru(1, ("день", "дня", "дней")) == "день"
        assert _plural_ru(2, ("день", "дня", "дней")) == "дня"
        assert _plural_ru(5, ("день", "дня", "дней")) == "дней"
        assert _plural_ru(11, ("день", "дня", "дней")) == "дней"
        assert _plural_ru(21, ("день", "дня", "дней")) == "день"
        assert _plural_ru(124, ("день", "дня", "дней")) == "дня"
