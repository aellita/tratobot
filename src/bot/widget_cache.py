"""Widget and photo message cache for monthly chart.

In-memory cache with per-user locks to prevent race conditions.
Keys: (telegram_id, chat_id) -> message_id
"""

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, InputMediaPhoto

logger = logging.getLogger(__name__)

# Widget cache: (telegram_id, chat_id) -> message_id
_widget_cache: dict[tuple[int, int], int] = {}
# Photo cache: (telegram_id, chat_id) -> message_id
_photo_cache: dict[tuple[int, int], int] = {}
# Per-user locks to prevent race conditions
_locks: dict[int, asyncio.Lock] = {}


def _get_lock(telegram_id: int) -> asyncio.Lock:
    """Get or create lock for user."""
    if telegram_id not in _locks:
        _locks[telegram_id] = asyncio.Lock()
    return _locks[telegram_id]


def _cache_key(telegram_id: int, chat_id: int) -> tuple[int, int]:
    return (telegram_id, chat_id)


# ─── Widget cache (legacy) ───


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


# ─── Photo cache (PNG card) ───


def set_photo_msg(telegram_id: int, chat_id: int, msg_id: int) -> None:
    """Store photo message_id for user in specific chat."""
    _photo_cache[(telegram_id, chat_id)] = msg_id
    logger.debug("Photo cache set for %s in chat %s: msg_id=%s", telegram_id, chat_id, msg_id)


def get_photo_msg(telegram_id: int, chat_id: int) -> int | None:
    """Get cached photo message_id for user in specific chat."""
    return _photo_cache.get((telegram_id, chat_id))


def clear_photo_msg(telegram_id: int, chat_id: int) -> None:
    """Remove cached photo message_id for user in specific chat."""
    _photo_cache.pop((telegram_id, chat_id), None)
    logger.debug("Photo cache cleared for %s in chat %s", telegram_id, chat_id)


async def send_or_update_photo(
    bot: Bot,
    telegram_id: int,
    chat_id: int,
    png_bytes: bytes,
    force_new: bool = False,
) -> int | None:
    """Send new photo or update existing one with proper locking and fallback.

    Args:
        bot: Bot instance
        telegram_id: User ID
        chat_id: Chat ID
        png_bytes: PNG image bytes
        force_new: Ignore the cached message and send a fresh photo

    Returns:
        message_id of sent/updated photo, or None on failure
    """
    lock = _get_lock(telegram_id)
    async with lock:
        if force_new:
            _photo_cache.pop((telegram_id, chat_id), None)
        cached_msg_id = get_photo_msg(telegram_id, chat_id)
        if cached_msg_id:
            try:
                await bot.edit_message_media(
                    chat_id=chat_id,
                    message_id=cached_msg_id,
                    media=InputMediaPhoto(
                        media=BufferedInputFile(png_bytes, filename="report.png")
                    ),
                )
                logger.debug("Photo updated for %s in chat %s", telegram_id, chat_id)
                return cached_msg_id
            except TelegramBadRequest as e:
                if "message is not modified" in str(e):
                    return cached_msg_id
                logger.warning("Photo edit failed, sending a new one: %s", e)
                _photo_cache.pop((telegram_id, chat_id), None)
        # Send new photo
        msg = await bot.send_photo(
            chat_id=chat_id,
            photo=BufferedInputFile(png_bytes, filename="report.png"),
            disable_notification=True,
        )
        _photo_cache[(telegram_id, chat_id)] = msg.message_id
        logger.debug(
            "Photo sent for %s in chat %s: msg_id=%s", telegram_id, chat_id, msg.message_id
        )
        return msg.message_id


def clear_all(telegram_id: int, chat_id: int) -> None:
    """Clear both widget and photo cache for user."""
    _widget_cache.pop((telegram_id, chat_id), None)
    _photo_cache.pop((telegram_id, chat_id), None)
    logger.debug("All cache cleared for %s in chat %s", telegram_id, chat_id)
