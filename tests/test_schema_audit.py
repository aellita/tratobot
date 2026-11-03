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
