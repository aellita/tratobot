"""Widget message cache for monthly chart.

In-memory cache with per-user locks to prevent race conditions.
Keys: (telegram_id, chat_id) -> message_id
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Widget cache: (telegram_id, chat_id) -> message_id
_widget_cache: dict[tuple[int, int], int] = {}
# Per-user locks to prevent race conditions
_widget_locks: dict[int, asyncio.Lock] = {}


def _get_lock(telegram_id: int) -> asyncio.Lock:
    """Get or create lock for user."""
    if telegram_id not in _widget_locks:
        _widget_locks[telegram_id] = asyncio.Lock()
    return _widget_locks[telegram_id]


def _cache_key(telegram_id: int, chat_id: int) -> tuple[int, int]:
    return (telegram_id, chat_id)


def set_widget_msg(telegram_id: int, chat_id: int, msg_id: int) -> None:
    """Store widget message_id for user in specific chat."""
    _widget_cache[_cache_key(telegram_id, chat_id)] = msg_id
    logger.debug("Widget cache set for %s in chat %s: msg_id=%s", telegram_id, chat_id, msg_id)


def get_widget_msg(telegram_id: int, chat_id: int) -> int | None:
    """Get cached widget message_id for user in specific chat."""
    return _widget_cache.get(_cache_key(telegram_id, chat_id))


def clear_widget_msg(telegram_id: int, chat_id: int) -> None:
    """Remove cached widget message_id for user in specific chat."""
    _widget_cache.pop(_cache_key(telegram_id, chat_id), None)
    logger.debug("Widget cache cleared for %s in chat %s", telegram_id, chat_id)


async def send_or_update_widget(
    bot: Any,
    telegram_id: int,
    chat_id: int,
    html: str,
    state_json: str,
    send_widget_fn: Any,
    edit_widget_fn: Any,
) -> int | None:
    """Send new widget or update existing one with proper locking and fallback.

    Args:
        bot: Bot instance
        telegram_id: User ID
        chat_id: Chat ID
        html: Widget HTML
        state_json: Widget state JSON
        send_widget_fn: Function to send widget
        edit_widget_fn: Function to edit widget

    Returns:
        message_id of sent/updated widget, or None on failure
    """
    lock = _get_lock(telegram_id)
    async with lock:
        cached_msg_id = get_widget_msg(telegram_id, chat_id)
        if cached_msg_id:
            # Try to edit existing widget
            result = await edit_widget_fn(bot, chat_id, cached_msg_id, state_json)
            if result is not None:
                logger.debug("Widget updated for %s in chat %s", telegram_id, chat_id)
                return cached_msg_id
            # Fallback: edit failed (message deleted, etc.) -> send new
            logger.warning(
                "edit_widget_data failed for %s in chat %s, sending new widget",
                telegram_id,
                chat_id,
            )
            clear_widget_msg(telegram_id, chat_id)

        # Send new widget
        result = await send_widget_fn(bot, chat_id, html, state_json)
        if result and result.get("message_id"):
            msg_id = result["message_id"]
            set_widget_msg(telegram_id, chat_id, msg_id)
            logger.debug("Widget sent for %s in chat %s: msg_id=%s", telegram_id, chat_id, msg_id)
            return msg_id
        else:
            logger.warning("send_widget failed for %s in chat %s", telegram_id, chat_id)
            return None
