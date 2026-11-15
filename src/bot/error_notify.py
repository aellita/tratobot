import html
import logging
import re
import traceback

logger = logging.getLogger(__name__)

_UPDATE_ATTRS = (
    "message",
    "edited_message",
    "business_message",
    "edited_business_message",
    "callback_query",
    "inline_query",
    "chosen_inline_result",
    "channel_post",
    "edited_channel_post",
    "poll_answer",
    "pre_checkout_query",
    "shipping_query",
    "my_chat_member",
    "chat_member",
)

_TB_LIMIT = 3000
_HTML_LIMIT = 3600
_PLAIN_LIMIT = 3800
_ENTITY_TAIL_RE = re.compile(r"&[a-zA-Z#0-9]*$")


def _update_kind(update) -> str:
    for attr in _UPDATE_ATTRS:
        if getattr(update, attr, None) is not None:
            return attr
    return "unknown"


def extract_user_id(update) -> int | None:
    for attr in _UPDATE_ATTRS:
        obj = getattr(update, attr, None)
        if obj is None:
            continue
        from_user = getattr(obj, "from_user", None) or getattr(obj, "user", None)
        if from_user is not None:
            return from_user.id
    return None


def extract_chat_id(update) -> int | None:
    """Чат, куда можно ответить пользователю (в т.ч. для callback)."""
    message = getattr(update, "message", None)
    if message is not None:
        return message.chat.id
    callback = getattr(update, "callback_query", None)
    if callback is not None and callback.message is not None:
        return callback.message.chat.id
    return None


def _truncate_escaped(text: str, limit: int) -> str:
    """Обрезать уже экранированный текст, не порвав HTML-сущность."""
    if len(text) <= limit:
        return text
    return _ENTITY_TAIL_RE.sub("", text[:limit])


def _traceback_tail(exception: BaseException) -> str:
    return "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))[
        -_TB_LIMIT:
    ]


def format_admin_error(update, exception: BaseException) -> str:
    tb = _truncate_escaped(html.escape(_traceback_tail(exception)), _HTML_LIMIT)
    user_id = extract_user_id(update)
    return (
        "<b>🐞 Ошибка в TratoBot</b>\n"
        f"update: <code>{_update_kind(update)}</code>\n"
        f"user_id: <code>{user_id if user_id is not None else '—'}</code>\n"
        f"exception: <code>{html.escape(type(exception).__name__)}</code>\n\n"
        f"<pre>{tb}</pre>"
    )


def format_plain_error(update, exception: BaseException) -> str:
    user_id = extract_user_id(update)
    tb = _traceback_tail(exception).replace("<", "").replace(">", "")
    text = (
        "🐞 Ошибка в TratoBot\n"
        f"update: {_update_kind(update)}\n"
        f"user_id: {user_id if user_id is not None else '—'}\n"
        f"exception: {type(exception).__name__}\n\n"
        f"{tb}"
    )
    return text[:_PLAIN_LIMIT]


async def notify_admin(bot, update, exception: BaseException, admin_id: int | None) -> bool:
    """Отправить traceback админу. Никогда не роняет обработчик."""
    if admin_id is None:
        return False
    try:
        await bot.send_message(admin_id, format_admin_error(update, exception))
        return True
    except Exception:
        logger.error("Failed to send HTML error report to admin, retrying plain", exc_info=True)

    try:
        await bot.send_message(admin_id, format_plain_error(update, exception), parse_mode=None)
        return True
    except Exception:
        logger.error("Failed to notify admin about error", exc_info=True)
        return False
