import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..core.config import settings
from ..db.models.models import Base

logger = logging.getLogger(__name__)

is_postgres = settings.DATABASE_URL.startswith("postgresql://")

ALLOWED_TABLES = {
    "budgets", "expenses", "categories", "wishlists",
    "black_day_funds", "user_settings", "users",
}
ALLOWED_COLUMNS = {
    "user_id", "telegram_id", "id", "period_start_day",
    "rounding_mode", "free_money",
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
            text("SELECT column_name FROM information_schema.columns "
                 "WHERE table_name = :table AND column_name = :col"),
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
            for table, old_col in [("budgets", "user_id"), ("expenses", "user_id"),
                                    ("categories", "user_id"), ("wishlists", "user_id"),
                                    ("black_day_funds", "user_id"), ("user_settings", "user_id")]:
                _validate_identifier(table, ALLOWED_TABLES)
                _validate_identifier(old_col, ALLOWED_COLUMNS)
                if await _has_column(conn, table, old_col):
                    await conn.execute(text(f"ALTER TABLE {table} RENAME COLUMN {old_col} TO telegram_id"))
                    logger.info(f"Migrated {table}: {old_col} → telegram_id")

            if await _has_column(conn, "users", "id"):
                await conn.execute(text("ALTER TABLE users DROP CONSTRAINT users_pkey CASCADE"))
                await conn.execute(text("ALTER TABLE users DROP COLUMN id"))
                await conn.execute(text("ALTER TABLE users ADD PRIMARY KEY (telegram_id)"))
                await conn.execute(text("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_telegram_id_key"))
                logger.info("Migrated users: telegram_id is now primary key")

            # Categories: make telegram_id and type nullable
            row = (await conn.execute(text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :col"
            ), {"table": "categories", "col": "telegram_id"})).fetchone()
            if row and row[0] == 'NO':
                await conn.execute(text("ALTER TABLE categories ALTER COLUMN telegram_id DROP NOT NULL"))
                logger.info("Migrated categories: telegram_id is now nullable")

            row = (await conn.execute(text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :col"
            ), {"table": "categories", "col": "type"})).fetchone()
            if row and row[0] == 'NO':
                await conn.execute(text("ALTER TABLE categories ALTER COLUMN type DROP NOT NULL"))
                logger.info("Migrated categories: type is now nullable")

        # Common migrations (both Postgres and SQLite): add missing columns
        if not await _has_column(conn, "budgets", "period_start_day"):
            if is_postgres:
                await conn.execute(text("ALTER TABLE budgets ADD COLUMN period_start_day INTEGER DEFAULT 1"))
            else:
                await conn.execute(text("ALTER TABLE budgets ADD COLUMN period_start_day INTEGER DEFAULT 1"))
            logger.info("Migrated budgets: added period_start_day")

        if not await _has_column(conn, "user_settings", "rounding_mode"):
            if is_postgres:
                await conn.execute(text("ALTER TABLE user_settings ADD COLUMN rounding_mode INTEGER DEFAULT 0"))
            else:
                await conn.execute(text("ALTER TABLE user_settings ADD COLUMN rounding_mode INTEGER DEFAULT 0"))
            logger.info("Migrated user_settings: added rounding_mode")

        if not await _has_column(conn, "budgets", "free_money"):
            if is_postgres:
                await conn.execute(text("ALTER TABLE budgets ADD COLUMN free_money FLOAT DEFAULT 0"))
            else:
                await conn.execute(text("ALTER TABLE budgets ADD COLUMN free_money REAL DEFAULT 0"))
            logger.info("Migrated budgets: added free_money")


async def close_db():
    await engine.dispose()
