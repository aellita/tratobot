"""Raw Telegram Bot API calls for Rich Messages (Bot API 10.1+) and Widgets (Bot API 10.4+).

Every outgoing inline keyboard must be tracked in ``_last_keyboard``
so that ``KeyboardCleanupMiddleware`` can clean it up on the next
user action — see agent/RULES.md § 12.2.4.
"""

import asyncio
import logging
from typing import Any

import aiohttp

from .middleware import _get_lock, _last_keyboard

logger = logging.getLogger(__name__)

# Shared aiohttp session for connection reuse
_http_session: aiohttp.ClientSession | None = None
_http_session_lock = asyncio.Lock()


async def _get_http_session() -> aiohttp.ClientSession:
    """Get or create shared HTTP session."""
    global _http_session
    async with _http_session_lock:
        if _http_session is None or _http_session.closed:
            _http_session = aiohttp.ClientSession()
        return _http_session


async def close_http_session() -> None:
    """Close the shared HTTP session (call on bot shutdown)."""
    global _http_session
    async with _http_session_lock:
        if _http_session is not None and not _http_session.closed:
            await _http_session.close()
        _http_session = None


async def _post_with_retry(url: str, payload: dict, max_retries: int = 3) -> dict | None:
    """POST with exponential backoff retry for transient errors."""
    session = await _get_http_session()
    for attempt in range(max_retries):
        try:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                if data.get("ok"):
                    return data["result"]
                if resp.status == 429:
                    retry_after = data.get("parameters", {}).get("retry_after", 1)
                    logger.warning("Rate limited, retrying after %ss", retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                # Don't retry client errors (4xx)
                if resp.status < 500:
                    logger.warning("API error (no retry): %s", data)
                    return None
        except Exception as e:
            logger.warning(
                "Request failed (attempt %d/%d): %s",
                attempt + 1,
                max_retries,
                type(e).__name__,
            )

        if attempt < max_retries - 1:
            await asyncio.sleep(0.5 * (2**attempt))  # 0.5s, 1s, 2s

    logger.error("All retries exhausted for %s", url.rsplit("/", 1)[-1])
    return None


async def send_widget(
    bot: Any,
    chat_id: int,
    html: str,
    state_json: str,
) -> dict | None:
    """Send a widget message (sendWidget).

    Returns message dict with message_id on success, None on failure.
    Errors are logged but don't raise — caller should handle gracefully.
    """
    url = f"https://api.telegram.org/bot{bot.token}/sendWidget"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "html": html,
        "chat_data": state_json,
        "disable_notification": True,
    }
    result = await _post_with_retry(url, payload)
    if result:
        msg_id = result.get("message_id")
        logger.debug("sendWidget ok for %s, message_id=%s", chat_id, msg_id)
    return result


async def edit_widget_data(
    bot: Any,
    chat_id: int,
    message_id: int,
    state_json: str,
) -> dict | None:
    """Edit widget data (editMessageWidgetData).

    Returns result dict on success, None on failure.
    Errors are logged but don't raise — caller should fallback to send_widget.
    """
    url = f"https://api.telegram.org/bot{bot.token}/editMessageWidgetData"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "chat_data": state_json,
    }
    result = await _post_with_retry(url, payload)
    if result:
        logger.debug("editMessageWidgetData ok for %s, message_id=%s", chat_id, message_id)
    return result


async def edit_rich_message(
    bot: Any,
    chat_id: int,
    message_id: int,
    html: str,
    reply_markup: Any = None,
) -> dict | None:
    url = f"https://api.telegram.org/bot{bot.token}/editMessageText"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "rich_message": {"html": html},
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup.model_dump(exclude_none=True)
    result = await _post(url, payload)
    if result is not None and _has_inline_keyboard(reply_markup):
        lock = _get_lock(chat_id)
        old_mids: set[int] = set()
        async with lock:
            s = _last_keyboard.setdefault(chat_id, set())
            old_mids = set(s)
            s.add(message_id)
            if len(s) > 5:
                s.pop()
            old_mids.discard(message_id)
        for old_id in old_mids:
            try:
                await bot.edit_message_reply_markup(
                    chat_id=chat_id, message_id=old_id, reply_markup=None
                )
            except Exception:
                pass
        async with lock:
            # ensure old are removed after edit
            s = _last_keyboard.get(chat_id)
            if s is not None:
                for oid in old_mids:
                    s.discard(oid)
    return result


async def send_rich_message(
    bot: Any,
    chat_id: int,
    html: str,
    reply_markup: Any = None,
) -> dict | None:
    url = f"https://api.telegram.org/bot{bot.token}/sendRichMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "rich_message": {"html": html},
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup.model_dump(exclude_none=True)
    result = await _post(url, payload)
    if result is not None and _has_inline_keyboard(reply_markup):
        msg_id = result.get("message_id")
        if msg_id:
            lock = _get_lock(chat_id)
            old_mids: set[int] = set()
            async with lock:
                s = _last_keyboard.setdefault(chat_id, set())
                old_mids = set(s)
                s.add(msg_id)
                if len(s) > 5:
                    s.pop()
                old_mids.discard(msg_id)
            for old_id in old_mids:
                try:
                    await bot.edit_message_reply_markup(
                        chat_id=chat_id, message_id=old_id, reply_markup=None
                    )
                except Exception:
                    pass
            async with lock:
                s = _last_keyboard.get(chat_id)
                if s is not None:
                    for oid in old_mids:
                        s.discard(oid)
    return result


def _has_inline_keyboard(reply_markup: Any) -> bool:
    if reply_markup is None:
        return False
    inline_kb = getattr(reply_markup, "inline_keyboard", None)
    return bool(inline_kb)


async def _post(url: str, payload: dict) -> dict | None:
    try:
        session = await _get_http_session()
        async with session.post(url, json=payload) as resp:
            data = await resp.json()
            if not data.get("ok"):
                logger.warning("Rich API error: %s", data)
                return None
            return data["result"]
    except Exception as e:
        logger.error("Rich API request failed: %s", type(e).__name__, exc_info=True)
        return None
