"""Tests for rich_api module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.rich_api import (
    close_http_session,
    edit_rich_message,
    edit_widget_data,
    send_rich_message,
    send_widget,
)


class TestSendWidget:
    """Tests for send_widget function."""

    @pytest.mark.asyncio
    async def test_send_widget_success(self):
        bot = MagicMock()
        bot.token = "test_token"

        with patch("src.bot.rich_api._post_with_retry", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"message_id": 123, "chat": {"id": 123}}

            result = await send_widget(bot, 123, "<html>test</html>", '{"m":"2026-11"}')

        assert result is not None
        assert result["message_id"] == 123
        mock_post.assert_called_once()
        payload = mock_post.call_args.args[1]
        assert payload["disable_notification"] is True

    @pytest.mark.asyncio
    async def test_send_widget_failure(self):
        bot = MagicMock()
        bot.token = "test_token"

        with patch("src.bot.rich_api._post_with_retry", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = None

            result = await send_widget(bot, 123, "<html>test</html>", '{"m":"2026-11"}')

        assert result is None


class TestEditWidgetData:
    """Tests for edit_widget_data function."""

    @pytest.mark.asyncio
    async def test_edit_widget_data_success(self):
        bot = MagicMock()
        bot.token = "test_token"

        with patch("src.bot.rich_api._post_with_retry", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"ok": True}

            result = await edit_widget_data(bot, 123, 456, '{"m":"2026-11"}')

        assert result is not None
        mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_edit_widget_data_failure(self):
        bot = MagicMock()
        bot.token = "test_token"

        with patch("src.bot.rich_api._post_with_retry", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = None

            result = await edit_widget_data(bot, 123, 456, '{"m":"2026-11"}')

        assert result is None


class TestRichMessage:
    """Tests for rich message functions."""

    @pytest.mark.asyncio
    async def test_edit_rich_message(self):
        bot = MagicMock()
        bot.token = "test_token"

        with patch("src.bot.rich_api._post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"message_id": 123}

            result = await edit_rich_message(bot, 123, 456, "<html>test</html>")

        assert result is not None
        assert result["message_id"] == 123

    @pytest.mark.asyncio
    async def test_send_rich_message(self):
        bot = MagicMock()
        bot.token = "test_token"

        with patch("src.bot.rich_api._post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"message_id": 123}

            result = await send_rich_message(bot, 123, "<html>test</html>")

        assert result is not None
        assert result["message_id"] == 123


class TestHttpSession:
    """Shared aiohttp session lifecycle."""

    @pytest.mark.asyncio
    async def test_close_http_session_is_idempotent(self):
        await close_http_session()
        await close_http_session()

    @pytest.mark.asyncio
    async def test_close_http_session_closes_shared_session(self):
        import src.bot.rich_api as rich_api

        session = MagicMock()
        session.closed = False
        session.close = AsyncMock()
        rich_api._http_session = session

        await close_http_session()

        session.close.assert_awaited_once()
        assert rich_api._http_session is None
