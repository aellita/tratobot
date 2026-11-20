"""Delivery of the monthly chart: PNG (primary) or native widget (flagged).

PNG is the reliable default because native Telegram widgets are currently
rolled back for security reasons. Widget code stays available behind
``settings.MONTHLY_WIDGET_ENABLED`` for when widgets return.
"""

import asyncio
import json
import logging

from aiogram import Bot

from ..core.config import settings
from ..db.models.models import Budget
from ..services.budget_service import get_base_daily_limit
from ..services.monthly_chart import (
    CHART_WIDGET_HTML,
    build_chart_data,
    build_chart_state,
    build_monthly_card_input,
    render_monthly_card_png,
)
from .rich_api import edit_widget_data, send_widget
from .widget_cache import get_widget_msg, send_or_update_photo, set_widget_msg

logger = logging.getLogger(__name__)


async def _send_widget_chart(
    bot: Bot,
    telegram_id: int,
    chat_id: int,
    state_json: str,
    force_new: bool,
) -> bool:
    """Try to edit an existing widget or send a new one. Returns success."""
    cached = None if force_new else get_widget_msg(telegram_id, chat_id)
    if cached:
        result = await edit_widget_data(bot, chat_id, cached, state_json)
        if result:
            return True
        logger.warning("Widget edit failed for %s, sending a new one", telegram_id)

    result = await send_widget(bot, chat_id, CHART_WIDGET_HTML, state_json)
    message_id = result.get("message_id") if result else None
    if message_id:
        set_widget_msg(telegram_id, chat_id, message_id)
        return True
    return False


async def send_monthly_chart(
    bot: Bot,
    telegram_id: int,
    chat_id: int,
    budget: Budget,
    prev_budget: Budget | None = None,
    force_new: bool = False,
) -> str:
    """Send or update the monthly chart.

    Returns ``"widget"``, ``"png"`` or ``"error"``.
    """
    daily_limit = await get_base_daily_limit(budget)

    if settings.MONTHLY_WIDGET_ENABLED:
        try:
            chart_data = await build_chart_data(telegram_id, budget)
            state = build_chart_state(telegram_id, budget, chart_data, daily_limit=daily_limit)
            state_json = json.dumps(state, separators=(",", ":"))
            if await _send_widget_chart(bot, telegram_id, chat_id, state_json, force_new):
                return "widget"
            logger.warning("Widget failed for %s, falling back to PNG", telegram_id)
        except Exception as e:
            logger.warning(
                "Widget delivery failed for %s (%s), falling back to PNG",
                telegram_id,
                e,
            )

    input_data = await build_monthly_card_input(
        telegram_id, budget, prev_budget, daily_limit=daily_limit
    )
    png_bytes = await asyncio.to_thread(render_monthly_card_png, input_data)
    message_id = await send_or_update_photo(
        bot, telegram_id, chat_id, png_bytes, force_new=force_new
    )
    if message_id is None:
        logger.error("Monthly PNG delivery failed for %s", telegram_id)
        return "error"
    return "png"
