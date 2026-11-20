"""Tests for widget_cache module."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest

from src.bot.widget_cache import (
    clear_all,
    clear_photo_msg,
    clear_widget_msg,
    get_photo_msg,
    get_widget_msg,
    send_or_update_photo,
    set_photo_msg,
    set_widget_msg,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_all(123, 456)
    yield
    clear_all(123, 456)


class TestWidgetCache:
    """Tests for widget message cache."""

    def test_set_and_get_widget_msg(self):
        set_widget_msg(123, 456, 789)
        assert get_widget_msg(123, 456) == 789
        assert get_widget_msg(123, 999) is None
        assert get_widget_msg(999, 456) is None

    def test_clear_widget_msg(self):
        set_widget_msg(123, 456, 789)
        clear_widget_msg(123, 456)
        assert get_widget_msg(123, 456) is None

    def test_clear_all(self):
        set_widget_msg(123, 456, 789)
        set_photo_msg(123, 456, 999)
        clear_all(123, 456)
        assert get_widget_msg(123, 456) is None
        assert get_photo_msg(123, 456) is None


class TestPhotoCache:
    """Tests for photo message cache."""

    def test_set_and_get_photo_msg(self):
        set_photo_msg(123, 456, 789)
        assert get_photo_msg(123, 456) == 789
        assert get_photo_msg(123, 999) is None
        assert get_photo_msg(999, 456) is None

    def test_clear_photo_msg(self):
        set_photo_msg(123, 456, 789)
        clear_photo_msg(123, 456)
        assert get_photo_msg(123, 456) is None


class TestSendOrUpdatePhoto:
    """Tests for send_or_update_photo function."""

    @pytest.mark.asyncio
    async def test_send_new_photo(self):
        bot = MagicMock()
        bot.send_photo = AsyncMock(return_value=MagicMock(message_id=123))

        result = await send_or_update_photo(bot, 123, 456, b"png")

        assert result == 123
        assert get_photo_msg(123, 456) == 123
        bot.send_photo.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_edit_existing_photo(self):
        set_photo_msg(123, 456, 789)
        bot = MagicMock()
        bot.edit_message_media = AsyncMock(return_value=MagicMock())
        bot.send_photo = AsyncMock()

        result = await send_or_update_photo(bot, 123, 456, b"png")

        assert result == 789
        bot.edit_message_media.assert_awaited_once()
        bot.send_photo.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fallback_on_message_not_found(self):
        set_photo_msg(123, 456, 789)
        bot = MagicMock()
        bot.edit_message_media = AsyncMock(
            side_effect=TelegramBadRequest(method=MagicMock(), message="message to edit not found")
        )
        bot.send_photo = AsyncMock(return_value=MagicMock(message_id=999))

        result = await send_or_update_photo(bot, 123, 456, b"png")

        assert result == 999
        assert get_photo_msg(123, 456) == 999
        bot.send_photo.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fallback_on_other_bad_request(self):
        set_photo_msg(123, 456, 789)
        bot = MagicMock()
        bot.edit_message_media = AsyncMock(
            side_effect=TelegramBadRequest(method=MagicMock(), message="message can't be edited")
        )
        bot.send_photo = AsyncMock(return_value=MagicMock(message_id=999))

        result = await send_or_update_photo(bot, 123, 456, b"png")

        assert result == 999
        assert get_photo_msg(123, 456) == 999

    @pytest.mark.asyncio
    async def test_force_new_skips_edit(self):
        set_photo_msg(123, 456, 789)
        bot = MagicMock()
        bot.edit_message_media = AsyncMock()
        bot.send_photo = AsyncMock(return_value=MagicMock(message_id=999))

        result = await send_or_update_photo(bot, 123, 456, b"png", force_new=True)

        assert result == 999
        bot.edit_message_media.assert_not_awaited()
        bot.send_photo.assert_awaited_once()
