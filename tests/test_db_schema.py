from sqlalchemy import inspect

from src.db.models.models import Base, DailyLimit


async def test_all_model_tables_are_created(engine):
    async with engine.connect() as conn:
        names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    assert set(Base.metadata.tables) <= set(names)


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
    assert table.c.plan_date.nullable is False

    foreign_keys = list(table.foreign_keys)
    assert len(foreign_keys) == 1
    assert foreign_keys[0].column.table.name == "users"
    assert foreign_keys[0].column.name == "telegram_id"
