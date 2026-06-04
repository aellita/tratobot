import time
from collections import defaultdict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

RATE_LIMIT = 0.7
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

        last = self._last_time[user_id]
        if now - last < RATE_LIMIT:
            return

        self._last_time[user_id] = now
        self._burst_counts[user_id].append(now)

        return await handler(event, data)
