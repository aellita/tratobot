from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from ..core.config import settings
from ..db.models.models import Base


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


async def close_db():
    await engine.dispose()