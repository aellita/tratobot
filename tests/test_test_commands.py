import pytest

from src.bot.handlers import test_commands
from src.core.config import Settings, settings
from src.utils import phrases


class _FakeUser:
    def __init__(self, user_id):
        self.id = user_id


class _FakeMessage:
    def __init__(self, user_id):
        self.from_user = _FakeUser(user_id)
        self.answers: list[str] = []

    async def answer(self, text, **kwargs):
        self.answers.append(text)


class _FakeEvent:
    def __init__(self, user):
        self.from_user = user


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

    async def _fake_send(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(test_commands, "send_morning_reports", _fake_send)

    await test_commands.cmd_test_morning(_FakeMessage(999), bot=object())

    assert calls == []


async def test_morning_runs_for_admin(monkeypatch, admins):
    calls = []

    async def _fake_send(bot, user_ids, *, force):
        calls.append((bot, user_ids, force))
        return list(user_ids)

    monkeypatch.setattr(test_commands, "send_morning_reports", _fake_send)
    bot = object()
    message = _FakeMessage(111)

    await test_commands.cmd_test_morning(message, bot=bot)

    assert calls == [(bot, [111], True)]
    assert message.answers == [
        phrases.TEST_MORNING_START,
        phrases.TEST_MORNING_SENT,
    ]


async def test_morning_reports_skip(monkeypatch, admins):
    async def _fake_send(bot, user_ids, *, force):
        return []

    monkeypatch.setattr(test_commands, "send_morning_reports", _fake_send)
    message = _FakeMessage(111)

    await test_commands.cmd_test_morning(message, bot=object())

    assert message.answers == [
        phrases.TEST_MORNING_START,
        phrases.TEST_MORNING_SKIPPED,
    ]


async def test_teaser_ignored_for_non_admin(monkeypatch, admins):
    calls = []

    async def _fake_teaser(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(test_commands, "send_evening_teaser", _fake_teaser)
    message = _FakeMessage(999)

    await test_commands.cmd_test_teaser(message, bot=object(), state=None)

    assert calls == []
    assert message.answers == []


async def test_teaser_runs_for_admin(monkeypatch, admins):
    calls = []
    storage = object()

    async def _fake_teaser(bot, teaser_storage, user_ids):
        calls.append((bot, teaser_storage, user_ids))
        return list(user_ids)

    monkeypatch.setattr(test_commands, "send_evening_teaser", _fake_teaser)
    message = _FakeMessage(111)
    bot = object()
    state = type("_State", (), {"storage": storage})()

    await test_commands.cmd_test_teaser(message, bot=bot, state=state)

    assert calls == [(bot, storage, [111])]
    assert message.answers == [phrases.TEST_TEASER_START, phrases.TEST_TEASER_SENT]


async def test_teaser_reports_skip(monkeypatch, admins):
    async def _fake_teaser(bot, teaser_storage, user_ids):
        return []

    monkeypatch.setattr(test_commands, "send_evening_teaser", _fake_teaser)
    message = _FakeMessage(111)
    state = type("_State", (), {"storage": object()})()

    await test_commands.cmd_test_teaser(message, bot=object(), state=state)

    assert message.answers == [phrases.TEST_TEASER_START, phrases.TEST_TEASER_SKIPPED]


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

    result = await test_commands.AdminOnlyMiddleware()(_handler, _FakeEvent(_FakeUser(999)), {})

    assert result is None
    assert calls == []


async def test_middleware_blocks_missing_user(admins):
    calls = []

    async def _handler(event, data):
        calls.append(event)

    result = await test_commands.AdminOnlyMiddleware()(_handler, _FakeEvent(None), {})

    assert result is None
    assert calls == []


async def test_middleware_allows_admin(admins):
    calls = []
    event = _FakeEvent(_FakeUser(111))

    async def _handler(event, data):
        calls.append(event)
        return "handled"

    result = await test_commands.AdminOnlyMiddleware()(_handler, event, {})

    assert result == "handled"
    assert calls == [event]


def test_middleware_registered_on_router():
    registered = test_commands.router.message.middleware._middlewares

    assert any(isinstance(m, test_commands.AdminOnlyMiddleware) for m in registered)
