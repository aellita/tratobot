import pytest

from src.bot.handlers import test_commands
from src.core.config import Settings, settings


class _FakeUser:
    def __init__(self, user_id):
        self.id = user_id


class _FakeMessage:
    def __init__(self, user_id):
        self.from_user = _FakeUser(user_id)
        self.answers: list[str] = []

    async def answer(self, text, **kwargs):
        self.answers.append(text)


class _NoUserMessage:
    from_user = None

    def __init__(self):
        self.answers: list[str] = []

    async def answer(self, text, **kwargs):
        self.answers.append(text)


@pytest.fixture
def admins(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_IDS", "111, 222")
    return {111, 222}


def test_admin_ids_parsing(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_IDS", " 111 , 222 ,x, -5 ")

    assert settings.admin_ids == {111, 222}


@pytest.mark.parametrize("raw", ["²", "--5", "111,,222", " ", "١٢٣", "", "1_000"])
def test_admin_ids_never_raise(monkeypatch, raw):
    monkeypatch.setattr(settings, "ADMIN_IDS", raw)

    assert isinstance(settings.admin_ids, set)


def test_admin_ids_from_real_settings():
    assert Settings(_env_file=None, ADMIN_IDS="111,222").admin_ids == {111, 222}


def test_empty_admin_ids_denies_everyone(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_IDS", "")

    assert settings.admin_ids == set()
    assert not test_commands._is_admin(_FakeMessage(111))


def test_is_admin_rejects_missing_user():
    assert not test_commands._is_admin(_NoUserMessage())


async def test_morning_ignored_for_non_admin(monkeypatch, admins):
    calls = []

    async def _fake_send(bot):
        calls.append(bot)

    monkeypatch.setattr(test_commands, "send_morning_reports", _fake_send)

    await test_commands.cmd_test_morning(_FakeMessage(999), bot=object())

    assert calls == []


async def test_morning_runs_for_admin(monkeypatch, admins):
    calls = []

    async def _fake_send(bot):
        calls.append(bot)

    monkeypatch.setattr(test_commands, "send_morning_reports", _fake_send)
    bot = object()

    await test_commands.cmd_test_morning(_FakeMessage(111), bot=bot)

    assert calls == [bot]


async def test_teaser_ignored_for_non_admin(monkeypatch, admins):
    calls = []

    async def _fake_teaser(bot, storage):
        calls.append(bot)

    monkeypatch.setattr(test_commands, "send_evening_teaser", _fake_teaser)
    message = _FakeMessage(999)

    await test_commands.cmd_test_teaser(message, bot=object(), state=None)

    assert calls == []
    assert message.answers == []


async def test_evening_ignored_for_non_admin(admins):
    message = _FakeMessage(999)

    await test_commands.cmd_test_evening(message, state=None)

    assert message.answers == []


async def test_monthly_summary_ignored_for_non_admin(admins):
    message = _FakeMessage(999)

    await test_commands.cmd_test_monthly_summary(message, bot=object())

    assert message.answers == []


async def test_middleware_blocks_non_admin(admins):
    calls = []

    async def _handler(event, data):
        calls.append(event)

    result = await test_commands.AdminOnlyMiddleware()(
        _handler, "event", {"event_from_user": _FakeUser(999)}
    )

    assert result is None
    assert calls == []


async def test_middleware_blocks_missing_user(admins):
    calls = []

    async def _handler(event, data):
        calls.append(event)

    result = await test_commands.AdminOnlyMiddleware()(_handler, "event", {})

    assert result is None
    assert calls == []


async def test_middleware_allows_admin(admins):
    calls = []

    async def _handler(event, data):
        calls.append(event)
        return "handled"

    result = await test_commands.AdminOnlyMiddleware()(
        _handler, "event", {"event_from_user": _FakeUser(111)}
    )

    assert result == "handled"
    assert calls == ["event"]
