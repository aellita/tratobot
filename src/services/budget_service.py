from datetime import datetime
from sqlalchemy import select

from ..db.database import async_session_maker
from ..db.models.models import Budget


async def save_budget(user_id: int, month: str, income: float, mandatory: float, black_day: float, wishlist_name: str = None, wishlist_price: float = 0):
    async with async_session_maker() as session:
        result = await session.execute(
            select(Budget).where(
                Budget.user_id == user_id,
                Budget.month == month
            )
        )
        budget = result.scalar_one_or_none()

        if budget:
            budget.total_income = income
            budget.mandatory_payments = mandatory
            budget.black_day_fund = black_day
            budget.wishlist_name = wishlist_name or "Мечта"
            budget.wishlist_target = wishlist_price
        else:
            budget = Budget(
                user_id=user_id,
                month=month,
                total_income=income,
                mandatory_payments=mandatory,
                black_day_fund=black_day,
                wishlist_name=wishlist_name or "Мечта",
                wishlist_target=wishlist_price
            )
            session.add(budget)

        await session.commit()


async def update_budget_field(user_id: int, field: str, value):
    month = datetime.now().strftime("%Y-%m")
    async with async_session_maker() as session:
        result = await session.execute(
            select(Budget).where(
                Budget.user_id == user_id,
                Budget.month == month
            )
        )
        budget = result.scalar_one_or_none()
        if budget:
            setattr(budget, field, value)
            await session.commit()
