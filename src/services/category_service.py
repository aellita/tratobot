from sqlalchemy import func, select

from ..db.database import async_session_maker
from ..db.models.models import Category, Expense


async def get_category_expense_count(
    telegram_id: int, category_id: int
) -> int:
    async with async_session_maker() as session:
        result = await session.execute(
            select(func.count(Expense.id)).where(
                Expense.telegram_id == telegram_id,
                Expense.category_id == category_id,
                Expense.is_deleted == False,
            )
        )
        return result.scalar() or 0


async def rename_category(telegram_id: int, category_id: int, new_name: str) -> bool:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Category).where(
                Category.id == category_id,
                Category.telegram_id == telegram_id,
            )
        )
        cat = result.scalar_one_or_none()
        if not cat:
            return False
        cat.name = new_name
        await session.commit()
        return True


async def toggle_archive_category(telegram_id: int, category_id: int) -> bool:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Category).where(
                Category.id == category_id,
                Category.telegram_id == telegram_id,
            )
        )
        cat = result.scalar_one_or_none()
        if not cat:
            return False
        cat.is_archived = not cat.is_archived
        await session.commit()
        return True


async def move_expenses_to_default_and_delete(
    telegram_id: int, category_id: int
) -> bool:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Category).where(
                Category.id == category_id,
                Category.telegram_id == telegram_id,
            )
        )
        cat = result.scalar_one_or_none()
        if not cat:
            return False

        default = await session.execute(
            select(Category).where(
                Category.telegram_id == telegram_id,
                Category.name == "Прочее",
            )
        )
        default_cat = default.scalar_one_or_none()
        new_cat_id = default_cat.id if default_cat else None

        await session.execute(
            Expense.__table__.update()
            .where(
                Expense.telegram_id == telegram_id,
                Expense.category_id == category_id,
            )
            .values(category_id=new_cat_id)
        )

        await session.delete(cat)
        await session.commit()
        return True


async def hard_delete_category(telegram_id: int, category_id: int) -> bool:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Category).where(
                Category.id == category_id,
                Category.telegram_id == telegram_id,
            )
        )
        cat = result.scalar_one_or_none()
        if not cat:
            return False

        await session.execute(
            Expense.__table__.delete()
            .where(
                Expense.telegram_id == telegram_id,
                Expense.category_id == category_id,
            )
        )

        await session.delete(cat)
        await session.commit()
        return True
