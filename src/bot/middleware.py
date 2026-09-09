import asyncio
import logging
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.methods.base import Response, TelegramMethod, TelegramType
from aiogram.types import CallbackQuery, Message, TelegramObject

logger = logging.getLogger(__name__)

# ── Global keyboard tracking cache (chat_id → set[message_id]) ──────────
# Stores up to 5 recent inline keyboards per chat so that concurrent
# sends (e.g. morning 08:00 + status) don't overwrite each other.
# Entries are removed on pop() when the user's next action triggers
# KeyboardCleanupMiddleware, so no TTL is needed.

_last_keyboard: dict[int, set[int]] = {}
_locks: dict[int, asyncio.Lock] = {}


def _get_lock(chat_id: int) -> asyncio.Lock:
    lock = _locks.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[chat_id] = lock
    return lock


class KeyboardCleanupMiddleware(BaseMiddleware):
    """Cleans up previous inline keyboard on incoming user action.

    Runs before every message / callback handler — pops the last tracked
    message_id from the global cache and removes its inline keyboard.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        bot = data.get("bot")
        chat_id: int | None = None
        if isinstance(event, Message):
            chat_id = event.chat.id
        elif isinstance(event, CallbackQuery) and event.message:
            chat_id = event.message.chat.id

        if chat_id is not None:
            lock = _get_lock(chat_id)
            async with lock:
                mids = _last_keyboard.pop(chat_id, set())
            for msg_id in mids:
                try:
                    await bot.edit_message_reply_markup(
                        chat_id=chat_id, message_id=msg_id, reply_markup=None
                    )
                except Exception:
                    pass

        return await handler(event, data)


class AutoTrackOutgoingMiddleware(BaseRequestMiddleware):
    """Tracks outgoing bot messages that carry an inline keyboard.

    Intercepts every API call the bot makes — if it is a successful
    SendMessage / EditMessageText / EditMessageReplyMarkup containing
    inline buttons, the message_id is stored in the global cache so that
    the next *inbound* middleware can clean it up.
    """

    async def __call__(
        self,
        make_request: Callable[..., Awaitable[Response[TelegramType]]],
        bot: Any,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        response = await make_request(bot, method)

        if isinstance(response, Response):
            if not response.ok:
                return response
            msg = response.result
        else:
            msg = response

        if isinstance(msg, Message) and msg.reply_markup:
            inline_kb = getattr(msg.reply_markup, "inline_keyboard", None)
            if inline_kb:
                lock = _get_lock(msg.chat.id)
                async with lock:
                    s = _last_keyboard.setdefault(msg.chat.id, set())
                    s.add(msg.message_id)
                    if len(s) > 5:
                        # keep most recent 5, drop oldest arbitrary
                        s.pop()

        return response


BURST_LIMIT = 5
BURST_WINDOW = 3.0


class RateLimitMiddleware(BaseMiddleware):
    def __init__(self):
        self._last_time = defaultdict(float)
        self._burst_counts = defaultdict(list)

    async def __call__(self, handler, event, data):
        user_id = getattr(getattr(event, "from_user", None), "id", None)
        if not user_id:
            return await handler(event, data)

        now = time.monotonic()

        window_start = now - BURST_WINDOW
        self._burst_counts[user_id] = [t for t in self._burst_counts[user_id] if t > window_start]
        if len(self._burst_counts[user_id]) >= BURST_LIMIT:
            if isinstance(event, Message):
                await event.answer("⏳ Слишком быстро. Сбавь темп.")
            elif isinstance(event, CallbackQuery):
                await event.answer("⏳ Слишком быстро", show_alert=False)
            return

        self._last_time[user_id] = now
        self._burst_counts[user_id].append(now)

        return await handler(event, data)


class DuplicateMiddleware(BaseMiddleware):
    WINDOW = 15.0

    def __init__(self):
        self._expenses: dict[int, list[dict]] = defaultdict(list)
        self._dup_count: dict[tuple[int, float, str], int] = defaultdict(int)
        self._pending: dict[int, dict] = {}
        self._last_message_id: dict[int, int] = {}

    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and event.text and event.from_user:
            user_id = event.from_user.id
            msg_id = event.message_id
            if self._last_message_id.get(user_id) == msg_id:
                last = self._get_last_expense(user_id)
                if last and last.get("response_text"):
                    await event.answer(last["response_text"])
                return
        return await handler(event, data)

    def _get_last_expense(self, user_id: int) -> dict | None:
        if not self._expenses[user_id]:
            return None
        return self._expenses[user_id][-1]

    def _cleanup(self, user_id: int):
        now = time.monotonic()
        self._expenses[user_id] = [
            e for e in self._expenses[user_id] if now - e["ts"] <= self.WINDOW
        ]

    def check(self, user_id: int, amount: float, description: str) -> str:
        self._cleanup(user_id)
        matches = [
            e
            for e in self._expenses[user_id]
            if e["amount"] == amount and e["description"] == description
        ]
        if not matches:
            return "new"

        key = (user_id, amount, description)
        self._dup_count[key] += 1
        if self._dup_count[key] == 1:
            return "warn"
        return "silent"

    def set_pending(
        self,
        user_id: int,
        amount: float,
        description: str,
        cat_id: int | None,
        corrected_desc: str,
        emoji: str,
        cat_name: str,
    ):
        self._pending[user_id] = {
            "amount": amount,
            "description": description,
            "cat_id": cat_id,
            "corrected_desc": corrected_desc,
            "emoji": emoji,
            "cat_name": cat_name,
        }

    def get_pending(self, user_id: int) -> dict | None:
        return self._pending.pop(user_id, None)

    def record(
        self,
        user_id: int,
        message_id: int,
        amount: float,
        description: str,
        expense_id: int,
        response_text: str = "",
    ):
        self._expenses[user_id].append(
            {
                "amount": amount,
                "description": description,
                "expense_id": expense_id,
                "ts": time.monotonic(),
                "response_text": response_text,
            }
        )
        self._last_message_id[user_id] = message_id
        self._dup_count[(user_id, amount, description)] = 0

    def reset_dup_count(self, user_id: int, amount: float, description: str):
        self._dup_count[(user_id, amount, description)] = 0

    def _cleanup_old_users(self):
        now = time.monotonic()
        cutoff = now - 86400
        stale = [
            uid
            for uid, exps in self._expenses.items()
            if not exps or all(now - e["ts"] > cutoff for e in exps)
        ]
        for user_id in stale:
            del self._expenses[user_id]
            self._last_message_id.pop(user_id, None)
            self._pending.pop(user_id, None)
            dup_keys = [k for k in self._dup_count if k[0] == user_id]
            for k in dup_keys:
                del self._dup_count[k]

    async def start_cleanup(self):
        while True:
            await asyncio.sleep(86400)
            self._cleanup_old_users()


dup_middleware = DuplicateMiddleware()
