import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..core.config import settings
from ..db.models.models import Base

logger = logging.getLogger(__name__)

is_postgres = settings.DATABASE_URL.startswith("postgresql://")

ALLOWED_TABLES = {
    "budgets",
    "expenses",
    "categories",
    "wishlists",
    "black_day_funds",
    "user_settings",
    "users",
    "daily_reports_log",
    "recovery_states",
    "recovery_offer_state",
}
ALLOWED_COLUMNS = {
    "user_id",
    "telegram_id",
    "id",
    "period_start_day",
    "rounding_mode",
    "free_money",
    "spent_at_recalc",
    "is_archived",
    "report_type",
    "sent_date",
    "base_daily_limit",
    "budget_id",
    "status",
    "completion_reason",
    "baseline",
    "target",
    "total_days",
    "initial_deficit",
    "initial_target",
    "initial_total_days",
    "started_at",
    "stopped_at",
    "completed_at",
    "created_at",
    "updated_at",
    "dismissed",
    "last_offer_at",
    "last_offer_deficit",
}


def _validate_identifier(name: str, allowed: set[str]):
    if name not in allowed:
        raise ValueError(f"Unauthorized SQL identifier: {name}")


engine = create_async_engine(
    settings.db_url,
    echo=False,
    pool_pre_ping=is_postgres,
    **({"connect_args": {"statement_cache_size": 0}} if is_postgres else {}),
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncSession:
    async with async_session_maker() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _has_column(conn, table: str, column: str) -> bool:
    _validate_identifier(table, ALLOWED_TABLES)
    _validate_identifier(column, ALLOWED_COLUMNS)
    if is_postgres:
        result = await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :col"
            ),
            {"table": table, "col": column},
        )
        return result.fetchone() is not None
    else:
        result = await conn.execute(text(f"PRAGMA table_info('{table}')"))
        rows = result.fetchall()
        return any(row[1] == column for row in rows)


async def migrate_schema():
    """Migrate old schema (user_id FK → telegram_id FK) to new schema."""
    async with engine.begin() as conn:
        if is_postgres:
            for table, old_col in [
                ("budgets", "user_id"),
                ("expenses", "user_id"),
                ("categories", "user_id"),
                ("wishlists", "user_id"),
                ("black_day_funds", "user_id"),
                ("user_settings", "user_id"),
            ]:
                _validate_identifier(table, ALLOWED_TABLES)
                _validate_identifier(old_col, ALLOWED_COLUMNS)
                if await _has_column(conn, table, old_col):
                    await conn.execute(
                        text(f"ALTER TABLE {table} RENAME COLUMN {old_col} TO telegram_id")
                    )
                    logger.info(f"Migrated {table}: {old_col} → telegram_id")

            if await _has_column(conn, "users", "id"):
                await conn.execute(text("ALTER TABLE users DROP CONSTRAINT users_pkey CASCADE"))
                await conn.execute(text("ALTER TABLE users DROP COLUMN id"))
                await conn.execute(text("ALTER TABLE users ADD PRIMARY KEY (telegram_id)"))
                await conn.execute(
                    text("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_telegram_id_key")
                )
                logger.info("Migrated users: telegram_id is now primary key")

            # Categories: make telegram_id and type nullable
            row = (
                await conn.execute(
                    text(
                        "SELECT is_nullable FROM information_schema.columns "
                        "WHERE table_name = :table AND column_name = :col"
                    ),
                    {"table": "categories", "col": "telegram_id"},
                )
            ).fetchone()
            if row and row[0] == "NO":
                await conn.execute(
                    text("ALTER TABLE categories ALTER COLUMN telegram_id DROP NOT NULL")
                )
                logger.info("Migrated categories: telegram_id is now nullable")

            row = (
                await conn.execute(
                    text(
                        "SELECT is_nullable FROM information_schema.columns "
                        "WHERE table_name = :table AND column_name = :col"
                    ),
                    {"table": "categories", "col": "type"},
                )
            ).fetchone()
            if row and row[0] == "NO":
                await conn.execute(text("ALTER TABLE categories ALTER COLUMN type DROP NOT NULL"))
                logger.info("Migrated categories: type is now nullable")

        # Common migrations (both Postgres and SQLite): add missing columns
        if not await _has_column(conn, "budgets", "period_start_day"):
            if is_postgres:
                await conn.execute(
                    text("ALTER TABLE budgets ADD COLUMN period_start_day INTEGER DEFAULT 1")
                )
            else:
                await conn.execute(
                    text("ALTER TABLE budgets ADD COLUMN period_start_day INTEGER DEFAULT 1")
                )
            logger.info("Migrated budgets: added period_start_day")

        if not await _has_column(conn, "user_settings", "rounding_mode"):
            if is_postgres:
                await conn.execute(
                    text("ALTER TABLE user_settings ADD COLUMN rounding_mode INTEGER DEFAULT 0")
                )
            else:
                await conn.execute(
                    text("ALTER TABLE user_settings ADD COLUMN rounding_mode INTEGER DEFAULT 0")
                )
            logger.info("Migrated user_settings: added rounding_mode")

        if not await _has_column(conn, "budgets", "free_money"):
            if is_postgres:
                await conn.execute(
                    text("ALTER TABLE budgets ADD COLUMN free_money FLOAT DEFAULT 0")
                )
            else:
                await conn.execute(text("ALTER TABLE budgets ADD COLUMN free_money REAL DEFAULT 0"))
            logger.info("Migrated budgets: added free_money")

        if not await _has_column(conn, "categories", "is_archived"):
            if is_postgres:
                await conn.execute(
                    text("ALTER TABLE categories ADD COLUMN is_archived BOOLEAN DEFAULT FALSE")
                )
            else:
                await conn.execute(
                    text("ALTER TABLE categories ADD COLUMN is_archived INTEGER DEFAULT 0")
                )
            logger.info("Migrated categories: added is_archived")

        if not await _has_column(conn, "budgets", "base_daily_limit"):
            if is_postgres:
                await conn.execute(
                    text("ALTER TABLE budgets ADD COLUMN base_daily_limit FLOAT DEFAULT NULL")
                )
            else:
                await conn.execute(
                    text("ALTER TABLE budgets ADD COLUMN base_daily_limit REAL DEFAULT NULL")
                )
            logger.info("Migrated budgets: added base_daily_limit")

        if not await _has_column(conn, "budgets", "spent_at_recalc"):
            if is_postgres:
                await conn.execute(
                    text("ALTER TABLE budgets ADD COLUMN spent_at_recalc FLOAT DEFAULT 0")
                )
            else:
                await conn.execute(text("ALTER TABLE budgets ADD COLUMN spent_at_recalc REAL DEFAULT 0"))
            logger.info("Migrated budgets: added spent_at_recalc")

        # Recovery tables (create if not exists via raw SQL for cross-DB compatibility)
        if is_postgres:
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS recovery_states (
                        id SERIAL PRIMARY KEY,
                        telegram_id BIGINT NOT NULL REFERENCES users(telegram_id),
                        budget_id INTEGER NOT NULL REFERENCES budgets(id),
                        status VARCHAR(20) NOT NULL,
                        completion_reason VARCHAR(20),
                        baseline FLOAT NOT NULL,
                        target FLOAT NOT NULL,
                        total_days INTEGER NOT NULL,
                        initial_deficit FLOAT NOT NULL,
                        initial_target FLOAT NOT NULL,
                        initial_total_days INTEGER NOT NULL,
                        started_at TIMESTAMP NOT NULL,
                        stopped_at TIMESTAMP,
                        completed_at TIMESTAMP,
                        created_at TIMESTAMP NOT NULL,
                        updated_at TIMESTAMP NOT NULL
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS recovery_offer_state (
                        telegram_id BIGINT PRIMARY KEY REFERENCES users(telegram_id),
                        dismissed BOOLEAN NOT NULL DEFAULT FALSE,
                        last_offer_at TIMESTAMP,
                        last_offer_deficit FLOAT
                    )
                    """
                )
            )
        else:
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS recovery_states (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        telegram_id BIGINT NOT NULL REFERENCES users(telegram_id),
                        budget_id INTEGER NOT NULL REFERENCES budgets(id),
                        status VARCHAR(20) NOT NULL,
                        completion_reason VARCHAR(20),
                        baseline FLOAT NOT NULL,
                        target FLOAT NOT NULL,
                        total_days INTEGER NOT NULL,
                        initial_deficit FLOAT NOT NULL,
                        initial_target FLOAT NOT NULL,
                        initial_total_days INTEGER NOT NULL,
                        started_at TIMESTAMP NOT NULL,
                        stopped_at TIMESTAMP,
                        completed_at TIMESTAMP,
                        created_at TIMESTAMP NOT NULL,
                        updated_at TIMESTAMP NOT NULL
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS recovery_offer_state (
                        telegram_id BIGINT PRIMARY KEY REFERENCES users(telegram_id),
                        dismissed INTEGER NOT NULL DEFAULT 0,
                        last_offer_at TIMESTAMP,
                        last_offer_deficit FLOAT
                    )
                    """
                )
            )
        logger.info("Migrated recovery: ensured recovery_states and recovery_offer_state")


async def close_db():
    await engine.dispose()
