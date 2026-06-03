from datetime import datetime, timezone
from unittest.mock import patch

import asyncio
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.db.models.models import Base, User, Budget, Wishlist, Expense, UserSettings

import src.db.database as _db
import src.services.budget_service as _bs
import src.services.goal_service as _gs
import src.services.expense_service as _es


TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def engine():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_maker(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def _patch_session_maker(session_maker, monkeypatch):
    for module in [_db, _bs, _gs, _es]:
        monkeypatch.setattr(module, "async_session_maker", session_maker)


@pytest_asyncio.fixture
async def db_session(session_maker):
    async with session_maker() as session:
        yield session


@pytest_asyncio.fixture
async def test_user(db_session):
    user = User(telegram_id=99999, username="testuser", first_name="Test")
    db_session.add(user)
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def test_budget(db_session, test_user):
    today = datetime.now()
    budget = Budget(
        telegram_id=99999,
        month=today.strftime("%Y-%m"),
        total_income=100000.0,
        mandatory_payments=30000.0,
        black_day_fund=10000.0,
        wishlist_name="PS5",
        wishlist_target=50000.0,
        period_start_day=1,
    )
    db_session.add(budget)
    await db_session.commit()
    return budget


@pytest_asyncio.fixture
async def test_goal(db_session, test_budget):
    goal = Wishlist(
        telegram_id=99999,
        name="PS5",
        target_amount=50000.0,
        current_amount=10000.0,
        is_active=True,
    )
    db_session.add(goal)
    await db_session.commit()
    return goal


@pytest_asyncio.fixture
async def test_expense(db_session, test_budget):
    expense = Expense(
        telegram_id=99999,
        amount=500.0,
        description="кофе",
        date=datetime.now(timezone.utc),
    )
    db_session.add(expense)
    await db_session.commit()
    return expense


@pytest_asyncio.fixture
async def test_settings(db_session, test_user):
    settings = UserSettings(
        telegram_id=99999,
        rounding_mode=10,
    )
    db_session.add(settings)
    await db_session.commit()
    return settings
