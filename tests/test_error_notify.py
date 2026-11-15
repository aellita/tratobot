import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.bot.error_notify import (
    extract_chat_id,
    extract_user_id,
    format_admin_error,
    format_plain_error,
    notify_admin,
)
from src.utils import phrases


def _update(user_id: int | None = 1001):
    if user_id is None:
        return SimpleNamespace()
    return SimpleNamespace(
        message=SimpleNamespace(
            from_user=SimpleNamespace(id=user_id),
            chat=SimpleNamespace(id=user_id),
        )
    )


def _raise_and_capture(message: str = "boom <tag>") -> BaseException:
    try:
        raise RuntimeError(message)
    except RuntimeError as exc:
        return exc


class TestExtractUserId:
    def test_message(self):
        assert extract_user_id(_update(42)) == 42

    def test_callback_query(self):
        update = SimpleNamespace(callback_query=SimpleNamespace(from_user=SimpleNamespace(id=77)))
        assert extract_user_id(update) == 77

    def test_edited_message(self):
        update = SimpleNamespace(edited_message=SimpleNamespace(from_user=SimpleNamespace(id=55)))
        assert extract_user_id(update) == 55

    def test_poll_answer_uses_user(self):
        update = SimpleNamespace(poll_answer=SimpleNamespace(user=SimpleNamespace(id=66)))
        assert extract_user_id(update) == 66

    def test_missing(self):
        assert extract_user_id(SimpleNamespace()) is None


class TestExtractChatId:
    def test_message(self):
        assert extract_chat_id(_update(42)) == 42

    def test_callback_query(self):
        update = SimpleNamespace(
            callback_query=SimpleNamespace(message=SimpleNamespace(chat=SimpleNamespace(id=77)))
        )
        assert extract_chat_id(update) == 77

    def test_callback_without_message(self):
        update = SimpleNamespace(
            callback_query=SimpleNamespace(message=None),
            message=None,
        )
        assert extract_chat_id(update) is None

    def test_missing(self):
        assert extract_chat_id(SimpleNamespace()) is None


class TestAdminMessage:
    def test_contains_user_id_and_traceback(self):
        exc = _raise_and_capture()
        text = format_admin_error(_update(1001), exc)

        assert "user_id: <code>1001</code>" in text
        assert "RuntimeError" in text
        assert "boom &lt;tag&gt;" in text
        assert "<pre>" in text
        assert "<b>🐞 Ошибка в TratoBot</b>" in text

    def test_reports_update_payload_kind(self):
        exc = _raise_and_capture()
        update = SimpleNamespace(
            message=None,
            callback_query=SimpleNamespace(from_user=SimpleNamespace(id=77)),
        )
        text = format_admin_error(update, exc)
        assert "update: <code>callback_query</code>" in text

    def test_missing_user_id_placeholder(self):
        text = format_admin_error(SimpleNamespace(), _raise_and_capture())
        assert "user_id: <code>—</code>" in text

    def test_html_is_escaped_and_bounded(self):
        exc = _raise_and_capture("<&>" * 5000)
        text = format_admin_error(_update(1001), exc)

        assert len(text) <= 4096
        assert "<pre>" in text
        assert text.rstrip().endswith("</pre>")

    def test_no_broken_html_entity_at_cut(self):
        exc = _raise_and_capture("&" * 5000)
        text = format_admin_error(_update(1001), exc)

        body = text.split("<pre>", 1)[1].rsplit("</pre>", 1)[0]
        assert re.search(r"&[a-zA-Z#0-9]*$", body) is None


class TestPlainFallback:
    def test_plain_text_has_no_tags_and_fits(self):
        exc = _raise_and_capture("<&>" * 5000)
        text = format_plain_error(_update(1001), exc)

        assert "<" not in text
        assert ">" not in text
        assert len(text) <= 4096
        assert "user_id: 1001" in text


class TestNotifyAdmin:
    async def test_sends_to_configured_admin(self):
        bot = SimpleNamespace(send_message=AsyncMock())
        exc = _raise_and_capture()

        ok = await notify_admin(bot, _update(1001), exc, admin_id=555)

        assert ok is True
        bot.send_message.assert_awaited_once()
        args, kwargs = bot.send_message.call_args
        assert args[0] == 555
        assert "user_id: <code>1001</code>" in args[1]

    async def test_no_admin_configured_is_noop(self):
        bot = SimpleNamespace(send_message=AsyncMock())

        ok = await notify_admin(bot, _update(1001), _raise_and_capture(), admin_id=None)

        assert ok is False
        bot.send_message.assert_not_awaited()

    async def test_send_failure_does_not_raise_and_retries_plain(self):
        bot = SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError("telegram down")))

        ok = await notify_admin(bot, _update(1001), _raise_and_capture(), admin_id=555)

        assert ok is False
        assert bot.send_message.await_count == 2
        assert bot.send_message.call_args.kwargs["parse_mode"] is None

    async def test_html_failure_falls_back_to_plain(self):
        bot = SimpleNamespace(
            send_message=AsyncMock(
                side_effect=[RuntimeError("can't parse entities"), None],
            )
        )

        ok = await notify_admin(bot, _update(1001), _raise_and_capture(), admin_id=555)

        assert ok is True
        assert bot.send_message.await_count == 2
        plain_call = bot.send_message.call_args
        assert plain_call.kwargs["parse_mode"] is None
        assert "user_id: 1001" in plain_call.args[1]


class TestErrorPhrase:
    def test_exact_user_facing_phrase(self):
        assert phrases.ERR_GENERIC == (
            "😨 Ой-ёёёй, случилась ошибочка!\n\nМы уже оповестили администратора."
        )


def test_config_has_admin_chat_id():
    from src.core.config import Settings

    field = Settings.model_fields["ADMIN_CHAT_ID"]
    assert field.default is None
    assert field.annotation == (int | None)


def test_config_empty_admin_chat_id_is_none():
    from src.core.config import Settings

    assert Settings(ADMIN_CHAT_ID="").ADMIN_CHAT_ID is None
    assert Settings(ADMIN_CHAT_ID="12345").ADMIN_CHAT_ID == 12345
