from datetime import datetime
from sqlalchemy import select

from ..db.database import async_session_maker
from ..db.models.models import User, Expense
from .categorization import detect_category


async def create_expense(telegram_id: int, amount: float, description: str) -> Expense | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            return None

        category = detect_category(description)

        expense = Expense(
            user_id=user.id,
            amount=amount,
            description=description or category,
            date=datetime.utcnow()
        )
        session.add(expense)
        await session.commit()
        return expense
