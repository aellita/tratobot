"""Tests for monthly_summary handlers (delivery + navigation)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.handlers.monthly_summary import _build_report_text, cmd_monthly_report
from src.db.models.models import Budget


def _budget(month: str) -> Budget:
    return Budget(
        id=1,
        telegram_id=99999,
        month=month,
        total_income=100000.0,
        mandatory_payments=20000.0,
        black_day_fund=10000.0,
        period_start_day=1,
    )


@pytest.mark.asyncio
async def test_empty_period_keeps_navigation_buttons():
    budgets = [_budget("2026-11"), _budget("2026-10")]

    with (
        patch(
            "src.bot.handlers.monthly_summary.get_all_budgets",
            new_callable=AsyncMock,
            return_value=budgets,
        ),
        patch(
            "src.bot.handlers.monthly_summary.build_summary_data",
            new_callable=AsyncMock,
            return_value={"total_spent": 0.0, "active": False},
        ),
    ):
        text, has_prev, has_next, prev_label, next_label = await _build_report_text(99999, 0)

    assert "трат" in text.lower() or "пусто" in text.lower() or text
    assert has_prev is True
    assert has_next is False
    assert prev_label
    assert next_label == ""


@pytest.mark.asyncio
async def test_cmd_monthly_report_sends_chart_once():
    budget = _budget("2026-11")
    callback = MagicMock()
    callback.from_user.id = 99999
    callback.message.chat.id = 456
    callback.message.message_id = 100
    callback.answer = AsyncMock()
    state = MagicMock()
    state.clear = AsyncMock()
    bot = MagicMock()

    with (
        patch(
            "src.bot.handlers.monthly_summary.get_all_budgets",
            new_callable=AsyncMock,
            return_value=[budget],
        ),
        patch("src.bot.handlers.monthly_summary.is_period_active", return_value=True),
        patch(
            "src.bot.handlers.monthly_summary.build_summary_data",
            new_callable=AsyncMock,
            return_value={"total_spent": 100.0, "active": True},
        ),
        patch(
            "src.bot.handlers.monthly_summary.format_summary_text",
            return_value="<p>report</p>",
        ),
        patch(
            "src.bot.handlers.monthly_summary.edit_rich_message",
            new_callable=AsyncMock,
        ) as mock_edit,
        patch(
            "src.bot.handlers.monthly_summary.send_monthly_chart",
            new_callable=AsyncMock,
        ) as mock_chart,
    ):
        await cmd_monthly_report(callback, state, bot)

    mock_edit.assert_awaited_once()
    mock_chart.assert_awaited_once()
    assert mock_chart.await_args.kwargs["force_new"] is True
    state.clear.assert_awaited_once()
