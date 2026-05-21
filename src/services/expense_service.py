from datetime import datetime
from sqlalchemy import select, func

from ..db.database import async_session_maker
from ..db.models.models import Expense

PAGE_SIZE = 5
IGNORE_WORDS = {"рублей", "рубля", "рубль", "руб", "₽", "р"}


def clean_description(text: str) -> str:
    for w in IGNORE_WORDS:
        text = text.replace(w, "")
    import re
    text = re.sub(r'[\s\+]+', ' ', text).strip()
    return text


def parse_expense_text(text: str) -> tuple[float, str] | None:
    import re
    numbers = re.findall(r'\d+(?:[,\.]\d+)?', text)
    total = 0.0
    for num_str in numbers:
        try:
            amount = float(num_str.replace(",", "."))
            if amount > 0:
                total += amount
        except:
            continue

    if total <= 0:
        return None

    description = text
    for num_str in numbers:
        description = description.replace(num_str, "")
    description = clean_description(description)

    return total, description


async def get_expense_page(telegram_id: int, page: int = 0) -> tuple[list[Expense], int, int]:
    async with async_session_maker() as session:
        total_q = await session.execute(
            select(func.count(Expense.id)).where(
                Expense.telegram_id == telegram_id,
                Expense.is_deleted == False
            )
        )
        total = total_q.scalar() or 0

        result = await session.execute(
            select(Expense)
            .where(
                Expense.telegram_id == telegram_id,
                Expense.is_deleted == False
            )
            .order_by(Expense.date.desc())
            .limit(PAGE_SIZE)
            .offset(page * PAGE_SIZE)
        )
        expenses = result.scalars().all()
        return expenses, total, (total + PAGE_SIZE - 1) // PAGE_SIZE


async def soft_delete_expense(telegram_id: int, expense_id: int) -> Expense | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Expense).where(
                Expense.id == expense_id,
                Expense.telegram_id == telegram_id,
                Expense.is_deleted == False
            )
        )
        expense = result.scalar_one_or_none()
        if not expense:
            return None

        expense.is_deleted = True
        await session.commit()
        return expense


async def restore_expense(telegram_id: int, expense_id: int) -> Expense | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Expense).where(
                Expense.id == expense_id,
                Expense.telegram_id == telegram_id,
                Expense.is_deleted == True
            )
        )
        expense = result.scalar_one_or_none()
        if not expense:
            return None

        expense.is_deleted = False
        await session.commit()
        return expense


async def update_expense_amount(telegram_id: int, expense_id: int, new_amount: float) -> Expense | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Expense).where(
                Expense.id == expense_id,
                Expense.telegram_id == telegram_id,
                Expense.is_deleted == False
            )
        )
        expense = result.scalar_one_or_none()
        if not expense:
            return None

        expense.amount = new_amount
        await session.commit()
        return expense
