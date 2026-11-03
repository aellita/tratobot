"""Read-only аудит расхождений между ORM-моделями и реальной БД.

Сверяет наличие таблиц/колонок, nullable и server default. **Типы и длины
(VARCHAR(20) vs VARCHAR(255), BIGINT vs INTEGER) не сравниваются.**

Exit codes: 0 — чисто, 1 — есть CRITICAL, 2 — не удалось прочитать схему.
"""

import asyncio
import logging
import sys
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import text

from .database import engine, is_postgres
from .models.models import Base

logger = logging.getLogger(__name__)

CRITICAL = "CRITICAL"
WARNING = "WARNING"
INFO = "INFO"


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    nullable: bool
    has_default: bool


@dataclass(frozen=True)
class Finding:
    level: str
    table: str
    column: str | None
    message: str

    def format(self) -> str:
        target = f"{self.table}.{self.column}" if self.column else self.table
        return f"[{self.level}] {target} — {self.message}"


def model_schema() -> dict[str, dict[str, ColumnInfo]]:
    schema: dict[str, dict[str, ColumnInfo]] = {}
    for table in Base.metadata.sorted_tables:
        schema[table.name] = {
            column.name: ColumnInfo(
                name=column.name,
                nullable=bool(column.nullable),
                has_default=column.server_default is not None,
            )
            for column in table.columns
        }
    return schema


def compare_schemas(
    model: Mapping[str, Mapping[str, ColumnInfo]],
    actual: Mapping[str, Mapping[str, ColumnInfo]],
) -> list[Finding]:
    findings: list[Finding] = []

    if not model:
        return [
            Finding(
                CRITICAL,
                "(models)",
                None,
                "модели не загружены — сверять нечего, аудит недостоверен",
            )
        ]

    for table_name, model_columns in model.items():
        actual_columns = actual.get(table_name)
        if actual_columns is None:
            findings.append(Finding(CRITICAL, table_name, None, "таблицы нет в базе"))
            continue

        for column_name, model_column in model_columns.items():
            actual_column = actual_columns.get(column_name)
            if actual_column is None:
                findings.append(
                    Finding(
                        CRITICAL, table_name, column_name, "колонки нет в базе (нужна миграция)"
                    )
                )
                continue
            if not model_column.nullable and actual_column.nullable:
                findings.append(
                    Finding(
                        WARNING,
                        table_name,
                        column_name,
                        "в базе допускает NULL, модель — нет",
                    )
                )
            elif model_column.nullable and not actual_column.nullable:
                level = WARNING if actual_column.has_default else CRITICAL
                findings.append(
                    Finding(
                        level,
                        table_name,
                        column_name,
                        "модель допускает NULL, база — нет — ORM INSERT с None упадёт",
                    )
                )

    for table_name, actual_columns in actual.items():
        model_columns = model.get(table_name)
        if model_columns is None:
            findings.append(Finding(INFO, table_name, None, "лишняя таблица (не из моделей)"))
            continue

        for column_name, actual_column in actual_columns.items():
            if column_name in model_columns:
                continue
            if not actual_column.nullable and not actual_column.has_default:
                findings.append(
                    Finding(
                        CRITICAL,
                        table_name,
                        column_name,
                        "legacy NOT NULL без server default — ORM INSERT упадёт",
                    )
                )
            else:
                findings.append(
                    Finding(WARNING, table_name, column_name, "legacy-колонка вне моделей")
                )

    return findings


async def _read_postgres(conn) -> dict[str, dict[str, ColumnInfo]]:
    result = await conn.execute(
        text(
            "SELECT c.table_name, c.column_name, c.is_nullable, c.column_default "
            "FROM information_schema.columns c "
            "JOIN information_schema.tables t "
            "ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
            "WHERE c.table_schema = ANY (current_schemas(false)) "
            "AND t.table_type = 'BASE TABLE' "
            "ORDER BY c.table_name, c.ordinal_position"
        )
    )
    schema: dict[str, dict[str, ColumnInfo]] = {}
    for table, column, nullable, default in result.fetchall():
        schema.setdefault(table, {})[column] = ColumnInfo(
            name=column,
            nullable=nullable == "YES",
            has_default=default is not None,
        )
    return schema


async def _read_sqlite(conn) -> dict[str, dict[str, ColumnInfo]]:
    tables = (
        (await conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'")))
        .scalars()
        .all()
    )
    schema: dict[str, dict[str, ColumnInfo]] = {}
    for table in tables:
        if table.startswith("sqlite_"):
            continue
        escaped = table.replace("'", "''")
        rows = (await conn.execute(text(f"PRAGMA table_xinfo('{escaped}')"))).fetchall()
        schema[table] = {
            row[1]: ColumnInfo(
                name=row[1],
                # INTEGER PRIMARY KEY — rowid alias, PRAGMA notnull=0, но NULL невозможен.
                nullable=not bool(row[3]) and not bool(row[5]),
                has_default=row[4] is not None,
            )
            for row in rows
        }
    return schema


async def read_actual_schema() -> dict[str, dict[str, ColumnInfo]]:
    async with engine.connect() as conn:
        if is_postgres:
            return await _read_postgres(conn)
        return await _read_sqlite(conn)


def report(findings: list[Finding]) -> int:
    critical = [f for f in findings if f.level == CRITICAL]
    warnings = [f for f in findings if f.level == WARNING]
    infos = [f for f in findings if f.level == INFO]

    for finding in critical + warnings + infos:
        print(finding.format())

    print(
        f"\nИтого: {len(critical)} critical, {len(warnings)} warning, {len(infos)} info",
    )
    if critical:
        print("ВЕРДИКТ: есть расхождения, которые сломают код. Не деплоить.")
        return 1
    print("ВЕРДИКТ: критичных расхождений нет.")
    return 0


async def run_audit() -> int:
    try:
        actual = await read_actual_schema()
    except Exception:
        logger.exception("Не удалось прочитать схему БД")
        print("ВЕРДИКТ: не удалось прочитать схему — проверь DATABASE_URL и доступность БД.")
        return 2
    findings = compare_schemas(model_schema(), actual)
    return report(findings)


def main() -> int:
    return asyncio.run(run_audit())


if __name__ == "__main__":
    sys.exit(main())
