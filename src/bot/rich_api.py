"""Raw Telegram Bot API calls for Rich Messages (Bot API 10.1+)."""

import logging
from typing import Any

import aiohttp

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
    return await _post(url, payload)


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
    return await _post(url, payload)


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
