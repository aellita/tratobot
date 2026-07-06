"""Raw Telegram Bot API calls for Rich Messages (Bot API 10.1+).

Every outgoing inline keyboard must be tracked in ``_last_keyboard``
so that ``KeyboardCleanupMiddleware`` can clean it up on the next
user action — see RULES.md § 12.2.4.
"""

import logging
from typing import Any

import aiohttp

from .middleware import _last_keyboard

logger = logging.getLogger(__name__)


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
        _last_keyboard[chat_id] = message_id
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
            _last_keyboard[chat_id] = msg_id
    return result


def _has_inline_keyboard(reply_markup: Any) -> bool:
    if reply_markup is None:
        return False
    inline_kb = getattr(reply_markup, "inline_keyboard", None)
    return bool(inline_kb)


async def _post(url: str, payload: dict) -> dict | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    logger.warning("Rich API error: %s", data)
                    return None
                return data["result"]
    except Exception as e:
        logger.error("Rich API request failed: %s", e, exc_info=True)
        return None
