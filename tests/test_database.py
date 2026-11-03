import pytest

from src.db import database


class _FakeResult:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        return []


class _FakeConn:
    def __init__(self, row=None, alter_raises=False):
        self.row = row
        self.alter_raises = alter_raises
        self.statements: list[str] = []

    def begin_nested(self):
        return _FakeTransaction(self)

    async def execute(self, statement, *args, **kwargs):
        self.statements.append(str(statement))
        if "ALTER TABLE users" in str(statement) and self.alter_raises:
            raise RuntimeError("lock timeout")
        if "information_schema.columns" in str(statement):
            return _FakeResult(self.row)
        return _FakeResult(None)


class _FakeTransaction:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeEngine:
    def __init__(self, conn):
        self.conn = conn

    def begin(self):
        return _FakeTransaction(self.conn)


def _alter_statements(conn):
    return [stmt for stmt in conn.statements if "ALTER TABLE users" in stmt]


@pytest.fixture
def postgres_mode(monkeypatch):
    monkeypatch.setattr(database, "is_postgres", True)


@pytest.fixture
def column_exists(monkeypatch):
    async def _has_column(conn, table, column):
        return True

    monkeypatch.setattr(database, "_has_column", _has_column)


@pytest.fixture
def column_missing(monkeypatch):
    async def _has_column(conn, table, column):
        return False

    monkeypatch.setattr(database, "_has_column", _has_column)


async def test_sets_default_for_legacy_not_null_column(postgres_mode, column_exists):
    conn = _FakeConn(row=[None])

    await database._ensure_user_is_active_default(conn)

    assert _alter_statements(conn) == ["ALTER TABLE users ALTER COLUMN is_active SET DEFAULT TRUE"]


async def test_overrides_false_default(postgres_mode, column_exists):
    conn = _FakeConn(row=["false"])

    await database._ensure_user_is_active_default(conn)

    assert _alter_statements(conn) == ["ALTER TABLE users ALTER COLUMN is_active SET DEFAULT TRUE"]


async def test_skips_when_default_already_true(postgres_mode, column_exists):
    conn = _FakeConn(row=["true"])

    await database._ensure_user_is_active_default(conn)

    assert _alter_statements(conn) == []


async def test_skips_when_column_absent(postgres_mode, column_missing):
    conn = _FakeConn(row=[None])

    await database._ensure_user_is_active_default(conn)

    assert conn.statements == []


async def test_skips_when_metadata_row_missing(postgres_mode, column_exists):
    conn = _FakeConn(row=None)

    await database._ensure_user_is_active_default(conn)

    assert _alter_statements(conn) == []


async def test_skips_on_sqlite(monkeypatch, column_exists):
    monkeypatch.setattr(database, "is_postgres", False)
    conn = _FakeConn(row=[None])

    await database._ensure_user_is_active_default(conn)

    assert conn.statements == []


async def test_migrate_schema_runs_fix_on_postgres(monkeypatch, postgres_mode, column_missing):
    calls = []

    async def _fake_fix(conn):
        calls.append(conn)

    conn = _FakeConn()
    monkeypatch.setattr(database, "_ensure_user_is_active_default", _fake_fix)
    monkeypatch.setattr(database, "engine", _FakeEngine(conn))

    await database.migrate_schema()

    assert calls == [conn]


async def test_migrate_schema_skips_fix_on_sqlite(monkeypatch, column_missing):
    calls = []

    async def _fake_fix(conn):
        calls.append(conn)

    conn = _FakeConn()
    monkeypatch.setattr(database, "is_postgres", False)
    monkeypatch.setattr(database, "_ensure_user_is_active_default", _fake_fix)
    monkeypatch.setattr(database, "engine", _FakeEngine(conn))

    await database.migrate_schema()

    assert calls == []


def test_is_active_is_allowed_identifier():
    assert "is_active" in database.ALLOWED_COLUMNS
    database._validate_identifier("is_active", database.ALLOWED_COLUMNS)


async def test_alter_failure_does_not_break_startup(postgres_mode, column_exists, caplog):
    conn = _FakeConn(row=[None], alter_raises=True)

    await database._ensure_user_is_active_default(conn)

    assert "Failed to set users.is_active default" in caplog.text


async def test_warns_when_metadata_row_missing(postgres_mode, column_exists, caplog):
    conn = _FakeConn(row=None)

    await database._ensure_user_is_active_default(conn)

    assert "default not applied" in caplog.text


async def test_metadata_query_scoped_to_search_path(postgres_mode, column_exists):
    conn = _FakeConn(row=["true"])

    await database._ensure_user_is_active_default(conn)

    assert any("current_schemas" in stmt for stmt in conn.statements)


async def test_has_column_scoped_to_search_path(postgres_mode):
    conn = _FakeConn(row=None)

    assert await database._has_column(conn, "users", "is_active") is False
    assert any("current_schemas" in stmt for stmt in conn.statements)
