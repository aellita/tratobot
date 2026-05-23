import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from ..core.config import settings
from ..db.models.models import Base

logger = logging.getLogger(__name__)

is_postgres = settings.DATABASE_URL.startswith("postgresql://")

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


async def migrate_schema():
    """Migrate old schema (user_id FK → telegram_id FK) to new schema."""
    if not is_postgres:
        logger.info("SQLite: recreating database for schema migration")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        return

    async with engine.begin() as conn:
        for table, old_col in [("budgets", "user_id"), ("expenses", "user_id"),
                                ("categories", "user_id"), ("wishlists", "user_id"),
                                ("black_day_funds", "user_id"), ("user_settings", "user_id")]:
            result = await conn.execute(text(
                f"SELECT column_name FROM information_schema.columns "
                f"WHERE table_name='{table}' AND column_name='{old_col}'"
            ))
            if result.fetchone():
                await conn.execute(text(f"ALTER TABLE {table} RENAME COLUMN {old_col} TO telegram_id"))
                logger.info(f"Migrated {table}: {old_col} → telegram_id")

        result = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='budgets' AND column_name='period_start_day'"
        ))
        if not result.fetchone():
            await conn.execute(text("ALTER TABLE budgets ADD COLUMN period_start_day INTEGER DEFAULT 1"))
            logger.info("Migrated budgets: added period_start_day")

        result = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='users' AND column_name='id'"
        ))
        if result.fetchone():
            await conn.execute(text("ALTER TABLE users DROP CONSTRAINT users_pkey CASCADE"))
            await conn.execute(text("ALTER TABLE users DROP COLUMN id"))
            await conn.execute(text("ALTER TABLE users ADD PRIMARY KEY (telegram_id)"))
            await conn.execute(text("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_telegram_id_key"))
            logger.info("Migrated users: telegram_id is now primary key")

        # Categories: make telegram_id and type nullable
        result = await conn.execute(text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name='categories' AND column_name='telegram_id'"
        ))
        row = result.fetchone()
        if row and row[0] == 'NO':
            await conn.execute(text("ALTER TABLE categories ALTER COLUMN telegram_id DROP NOT NULL"))
            logger.info("Migrated categories: telegram_id is now nullable")

        result = await conn.execute(text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name='categories' AND column_name='type'"
        ))
        row = result.fetchone()
        if row and row[0] == 'NO':
            await conn.execute(text("ALTER TABLE categories ALTER COLUMN type DROP NOT NULL"))
            logger.info("Migrated categories: type is now nullable")


async def close_db():
    await engine.dispose()