"""Integration tests for monthly chart data building and delivery."""

from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.chart_delivery import send_monthly_chart
from src.core.config import settings
from src.db.models.models import Budget, Expense
from src.services.monthly_chart import build_monthly_card_input, render_monthly_card_png
from src.utils.helpers import get_msk_now


def _period_start_date(budget: Budget) -> datetime:
    from src.services.monthly_report import get_period_dates

    return get_period_dates(budget)[0]


@pytest.mark.asyncio
async def test_build_monthly_card_input_uses_dates_and_real_expenses(db_session, test_budget):
    start = _period_start_date(test_budget)
    expense = Expense(
        telegram_id=99999,
        amount=500.0,
        description="кофе",
        date=start.replace(hour=12, minute=0, second=0, microsecond=0),
    )
    db_session.add(expense)
    await db_session.commit()

    input_data = await build_monthly_card_input(99999, test_budget)

    assert isinstance(input_data.period_start, date)
    assert not isinstance(input_data.period_start, datetime)
    assert isinstance(input_data.period_end, date)
    assert input_data.expenses_count == 1
    assert input_data.expenses[0]["amount"] == 500.0
    assert input_data.total_spent == 500.0
    # Active period must be capped at today, not the whole month.
    assert len(input_data.daily_spent) == get_msk_now().day
    assert input_data.daily_spent[0] == 500.0
    assert input_data.daily_limit > 0
    # The renderer must accept the service-produced input without errors.
    assert len(render_monthly_card_png(input_data)) > 1000


@pytest.mark.asyncio
async def test_build_monthly_card_input_passes_previous_period(db_session, test_budget):
    today = get_msk_now()
    prev_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    prev_budget = Budget(
        telegram_id=99999,
        month=prev_month,
        total_income=90000.0,
        mandatory_payments=20000.0,
        black_day_fund=10000.0,
        period_start_day=1,
    )
    db_session.add(prev_budget)
    await db_session.commit()

    prev_start = _period_start_date(prev_budget)
    db_session.add(
        Expense(
            telegram_id=99999,
            amount=700.0,
            description="прошлый период",
            date=prev_start.replace(hour=12, minute=0, second=0, microsecond=0),
        )
    )
    await db_session.commit()

    input_data = await build_monthly_card_input(99999, test_budget, prev_budget)

    assert input_data.prev_expenses is not None
    assert len(input_data.prev_expenses) == 1
    assert input_data.prev_expenses[0]["amount"] == 700.0
    assert isinstance(input_data.prev_period_start, date)
    assert input_data.prev_period_start < input_data.period_start
    assert input_data.prev_income > 0


@pytest.mark.asyncio
async def test_send_monthly_chart_widget_value_error_falls_back(db_session, test_budget):
    bot = MagicMock()
    with (
        patch.object(settings, "MONTHLY_WIDGET_ENABLED", True),
        patch("src.bot.chart_delivery.build_chart_state", side_effect=ValueError("too big")),
        patch("src.bot.chart_delivery.send_or_update_photo", new_callable=AsyncMock) as mock_png,
    ):
        mock_png.return_value = 123
        result = await send_monthly_chart(bot, 99999, 456, test_budget)

    assert result == "png"
    mock_png.assert_awaited_once()


@pytest.mark.asyncio
async def test_build_monthly_card_input_respects_frozen_limit(db_session, test_budget):
    test_budget.base_daily_limit = 1234.5
    input_data = await build_monthly_card_input(99999, test_budget)

    assert input_data.daily_limit == 1234.5


@pytest.mark.asyncio
async def test_send_monthly_chart_png_is_primary(db_session, test_budget):
    bot = MagicMock()
    with (
        patch.object(settings, "MONTHLY_WIDGET_ENABLED", False),
        patch("src.bot.chart_delivery.send_or_update_photo", new_callable=AsyncMock) as mock_send,
    ):
        mock_send.return_value = 123
        result = await send_monthly_chart(bot, 99999, 456, test_budget, force_new=True)

    assert result == "png"
    mock_send.assert_awaited_once()
    assert mock_send.await_args.kwargs["force_new"] is True


@pytest.mark.asyncio
async def test_send_monthly_chart_widget_when_enabled(db_session, test_budget):
    bot = MagicMock()
    with (
        patch.object(settings, "MONTHLY_WIDGET_ENABLED", True),
        patch("src.bot.chart_delivery._send_widget_chart", new_callable=AsyncMock) as mock_widget,
        patch("src.bot.chart_delivery.send_or_update_photo", new_callable=AsyncMock) as mock_png,
    ):
        mock_widget.return_value = True
        result = await send_monthly_chart(bot, 99999, 456, test_budget)

    assert result == "widget"
    mock_widget.assert_awaited_once()
    mock_png.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_monthly_chart_falls_back_to_png(db_session, test_budget):
    bot = MagicMock()
    with (
        patch.object(settings, "MONTHLY_WIDGET_ENABLED", True),
        patch("src.bot.chart_delivery._send_widget_chart", new_callable=AsyncMock) as mock_widget,
        patch("src.bot.chart_delivery.send_or_update_photo", new_callable=AsyncMock) as mock_png,
    ):
        mock_widget.return_value = False
        mock_png.return_value = 123
        result = await send_monthly_chart(bot, 99999, 456, test_budget)

    assert result == "png"
    mock_png.assert_awaited_once()
