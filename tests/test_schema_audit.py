from src.db import schema_audit
from src.db.schema_audit import (
    CRITICAL,
    INFO,
    WARNING,
    ColumnInfo,
    compare_schemas,
    model_schema,
)


def _column(name, nullable=False, has_default=False):
    return ColumnInfo(name=name, nullable=nullable, has_default=has_default)


def test_clean_schema_has_no_findings():
    model = {"users": {"telegram_id": _column("telegram_id")}}
    actual = {"users": {"telegram_id": _column("telegram_id")}}

    assert compare_schemas(model, actual) == []


def test_missing_table_is_critical():
    findings = compare_schemas({"users": {"id": _column("id")}}, {})

    assert [f.level for f in findings] == [CRITICAL]
    assert findings[0].message.startswith("таблицы нет")


def test_missing_column_is_critical():
    model = {"users": {"telegram_id": _column("telegram_id"), "created_at": _column("created_at")}}
    actual = {"users": {"telegram_id": _column("telegram_id")}}

    findings = compare_schemas(model, actual)

    assert len(findings) == 1
    assert findings[0].level == CRITICAL
    assert findings[0].column == "created_at"


def test_legacy_not_null_without_default_is_critical():
    model = {"users": {"telegram_id": _column("telegram_id")}}
    actual = {
        "users": {
            "telegram_id": _column("telegram_id"),
            "is_active": _column("is_active", nullable=False, has_default=False),
        }
    }

    findings = compare_schemas(model, actual)

    assert len(findings) == 1
    assert findings[0].level == CRITICAL
    assert findings[0].column == "is_active"


def test_legacy_not_null_with_default_is_warning():
    model = {"users": {"telegram_id": _column("telegram_id")}}
    actual = {
        "users": {
            "telegram_id": _column("telegram_id"),
            "is_active": _column("is_active", nullable=False, has_default=True),
        }
    }

    findings = compare_schemas(model, actual)

    assert [f.level for f in findings] == [WARNING]


def test_legacy_nullable_column_is_warning():
    model = {"users": {"telegram_id": _column("telegram_id")}}
    actual = {
        "users": {
            "telegram_id": _column("telegram_id"),
            "nickname": _column("nickname", nullable=True),
        }
    }

    findings = compare_schemas(model, actual)

    assert [f.level for f in findings] == [WARNING]


def test_extra_table_is_info():
    model = {"users": {"telegram_id": _column("telegram_id")}}
    actual = {
        "users": {"telegram_id": _column("telegram_id")},
        "old_backup": {"id": _column("id")},
    }

    findings = compare_schemas(model, actual)

    assert [f.level for f in findings] == [INFO]


def test_nullable_drift_is_warning():
    model = {"users": {"username": _column("username", nullable=False)}}
    actual = {"users": {"username": _column("username", nullable=True)}}

    findings = compare_schemas(model, actual)

    assert [f.level for f in findings] == [WARNING]
    assert "NULL" in findings[0].message


def test_model_schema_covers_all_tables():
    schema = model_schema()

    assert "users" in schema
    assert "budgets" in schema
    assert schema["users"]["telegram_id"].nullable is False


def test_model_nullable_but_db_not_null_is_critical():
    model = {"users": {"nickname": _column("nickname", nullable=True)}}
    actual = {"users": {"nickname": _column("nickname", nullable=False)}}

    findings = compare_schemas(model, actual)

    assert [f.level for f in findings] == [CRITICAL]
    assert "None" in findings[0].message


def test_model_nullable_but_db_not_null_with_default_is_warning():
    model = {"users": {"nickname": _column("nickname", nullable=True)}}
    actual = {"users": {"nickname": _column("nickname", nullable=False, has_default=True)}}

    findings = compare_schemas(model, actual)

    assert [f.level for f in findings] == [WARNING]


def test_empty_model_is_critical():
    findings = compare_schemas({}, {"users": {"id": _column("id")}})

    assert [f.level for f in findings] == [CRITICAL]
    assert findings[0].table == "(models)"


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakePgConn:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    async def execute(self, statement):
        self.statements.append(str(statement))
        return _FakeResult(self.rows)


class _FakeSqliteConn:
    def __init__(self, tables, pragma_rows):
        self.tables = tables
        self.pragma_rows = pragma_rows
        self.statements = []

    async def execute(self, statement):
        self.statements.append(str(statement))
        if "sqlite_master" in str(statement):
            return _FakeResult(self.tables)
        return _FakeResult(self.pragma_rows)


async def test_read_postgres_maps_information_schema():
    conn = _FakePgConn(
        [
            ("users", "is_active", "NO", None),
            ("users", "username", "YES", None),
            ("users", "created_at", "NO", "now()"),
        ]
    )

    schema = await schema_audit._read_postgres(conn)

    assert schema["users"]["is_active"].nullable is False
    assert schema["users"]["is_active"].has_default is False
    assert schema["users"]["username"].nullable is True
    assert schema["users"]["created_at"].has_default is True
    assert "current_schemas" in conn.statements[0]
    assert "BASE TABLE" in conn.statements[0]


async def test_read_sqlite_uses_table_xinfo_and_skips_internal_tables():
    conn = _FakeSqliteConn(
        ["users", "sqlite_sequence"],
        [
            [0, "telegram_id", "INTEGER", 1, None, 1, 0],
            [1, "is_active", "BOOLEAN", 1, None, 0, 0],
            [2, "nickname", "TEXT", 0, None, 0, 0],
        ],
    )

    schema = await schema_audit._read_sqlite(conn)

    assert set(schema) == {"users"}
    assert schema["users"]["telegram_id"].nullable is False  # PK rowid alias
    assert schema["users"]["is_active"].nullable is False
    assert schema["users"]["nickname"].nullable is True
    assert any("table_xinfo" in stmt for stmt in conn.statements)


def test_report_returns_1_on_critical(capsys):
    findings = [schema_audit.Finding(CRITICAL, "users", "is_active", "boom")]

    assert schema_audit.report(findings) == 1
    assert "Не деплоить" in capsys.readouterr().out


def test_report_returns_0_when_clean(capsys):
    assert schema_audit.report([]) == 0
    assert "критичных расхождений нет" in capsys.readouterr().out


async def test_run_audit_returns_2_when_read_fails(monkeypatch, capsys):
    async def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(schema_audit, "read_actual_schema", _boom)

    assert await schema_audit.run_audit() == 2
    assert "не удалось прочитать схему" in capsys.readouterr().out
