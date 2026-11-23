"""Integration tests for monthly chart data building and delivery."""

from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.chart_delivery import send_monthly_chart
from src.core.config import settings
from src.db.models.models import Budget, Category, Expense
from src.services.daily_limits import upsert_daily_limit
from src.services.monthly_chart import build_monthly_card_input, render_monthly_card_png
from src.services.recovery_service import create_recovery
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
    assert input_data.is_active is True
    assert input_data.upcoming is False
    assert input_data.as_of == get_msk_now().date()
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
async def test_build_monthly_card_input_uses_daily_limit_snapshots(db_session, test_budget):
    today = get_msk_now().date()
    period_start = today.replace(day=1)
    await upsert_daily_limit(99999, period_start, 111.0)

    input_data = await build_monthly_card_input(99999, test_budget)

    assert len(input_data.daily_limits) == len(input_data.daily_spent)
    assert input_data.daily_limits[0] == 111.0
    if len(input_data.daily_limits) > 1:
        assert input_data.daily_limits[1] == input_data.daily_limit


@pytest.mark.asyncio
async def test_build_monthly_card_input_uses_recovery_target_as_current_limit(
    db_session, test_budget
):
    await create_recovery(99999, test_budget.id, 1000, 300, 10, 5000)

    input_data = await build_monthly_card_input(99999, test_budget)

    assert input_data.current_limit == 300.0
    assert input_data.daily_limit != input_data.current_limit


@pytest.mark.asyncio
async def test_build_monthly_card_input_includes_expense_category(db_session, test_budget):
    category = Category(telegram_id=99999, name="Еда")
    db_session.add(category)
    await db_session.commit()
    start = _period_start_date(test_budget)
    db_session.add(
        Expense(
            telegram_id=99999,
            category_id=category.id,
            amount=700.0,
            description="обед",
            date=start.replace(hour=12, minute=0, second=0, microsecond=0),
        )
    )
    await db_session.commit()

    input_data = await build_monthly_card_input(99999, test_budget)

    assert input_data.expenses[0]["category"] == "Еда"


@pytest.mark.asyncio
async def test_build_monthly_card_input_clamps_available_income(db_session, test_budget):
    test_budget.total_income = 100.0
    test_budget.mandatory_payments = 200.0
    test_budget.black_day_fund = 0.0
    await db_session.commit()

    input_data = await build_monthly_card_input(99999, test_budget)

    assert input_data.available_income == 0.0


@pytest.mark.asyncio
async def test_build_monthly_card_input_uses_provided_current_limit(
    db_session, test_budget, monkeypatch
):
    async def boom(*args, **kwargs):
        raise AssertionError("effective limit must not be recomputed")

    monkeypatch.setattr("src.services.daily_limits.get_effective_daily_limit", boom)

    input_data = await build_monthly_card_input(99999, test_budget, current_limit=1234.0)

    assert input_data.current_limit == 1234.0


@pytest.mark.asyncio
async def test_send_monthly_chart_does_not_borrow_active_limit_for_other_budget(
    db_session, test_budget
):
    other = Budget(
        telegram_id=99999,
        month="2020-01",
        total_income=100000.0,
        mandatory_payments=0.0,
        black_day_fund=0.0,
        period_start_day=1,
        base_daily_limit=1000.0,
    )
    with (
        patch.object(settings, "MONTHLY_WIDGET_ENABLED", False),
        patch(
            "src.services.daily_limits.refresh_daily_limit",
            new=AsyncMock(return_value=(9999.0, "plan")),
        ),
        patch(
            "src.bot.chart_delivery.get_active_budget",
            new=AsyncMock(return_value=test_budget),
        ),
        patch(
            "src.bot.chart_delivery.build_monthly_card_input",
            new=AsyncMock(return_value=MagicMock()),
        ) as build_mock,
        patch("src.bot.chart_delivery.render_monthly_card_png", return_value=b"png"),
        patch("src.bot.chart_delivery.send_or_update_photo", new=AsyncMock(return_value=1)),
    ):
        result = await send_monthly_chart(MagicMock(), 99999, 456, other)

    assert result == "png"
    assert build_mock.await_args.kwargs["current_limit"] is None


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
