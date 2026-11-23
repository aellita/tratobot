import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from src.db.database import ALLOWED_TABLES
from src.db.models.models import Base, DailyLimit
from src.utils.helpers import get_msk_now


async def test_all_model_tables_are_created_and_allowed(engine):
    async with engine.connect() as conn:
        names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    assert set(names) == ALLOWED_TABLES
    assert set(Base.metadata.tables) == ALLOWED_TABLES


def test_daily_limits_columns_primary_key_and_foreign_key():
    table = DailyLimit.__table__

    assert set(table.columns.keys()) == {
        "telegram_id",
        "plan_date",
        "limit",
        "source",
        "updated_at",
    }
    assert [column.name for column in table.primary_key.columns] == [
        "telegram_id",
        "plan_date",
    ]
    assert table.c.limit.nullable is False
    assert table.c.source.nullable is False
    assert table.c.plan_date.nullable is False

    foreign_keys = list(table.foreign_keys)
    assert len(foreign_keys) == 1
    assert foreign_keys[0].column.table.name == "users"
    assert foreign_keys[0].column.name == "telegram_id"


async def test_duplicate_day_is_rejected_by_primary_key(db_session):
    from src.db.models.models import User

    db_session.add(User(telegram_id=1001))
    await db_session.commit()
    today = get_msk_now().date()
    db_session.add(DailyLimit(telegram_id=1001, plan_date=today, limit=1000.0, source="plan"))
    await db_session.commit()

    db_session.add(DailyLimit(telegram_id=1001, plan_date=today, limit=2000.0, source="recovery"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
