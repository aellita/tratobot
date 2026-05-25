from datetime import datetime
from sqlalchemy import select

from ..db.database import async_session_maker
from ..db.models.models import Budget


async def save_budget(telegram_id: int, month: str, income: float, mandatory: float, black_day: float, wishlist_name: str = None, wishlist_price: float = 0, period_start_day: int = 1):
    async with async_session_maker() as session:
        result = await session.execute(
            select(Budget).where(
                Budget.telegram_id == telegram_id,
                Budget.month == month
            )
        )
        budget = result.scalar_one_or_none()

        if budget:
            budget.total_income = income
            budget.mandatory_payments = mandatory
            budget.black_day_fund = black_day
            budget.wishlist_name = wishlist_name or "Хотелка"
            budget.wishlist_target = wishlist_price
            budget.period_start_day = period_start_day
        else:
            budget = Budget(
                telegram_id=telegram_id,
                month=month,
                total_income=income,
                mandatory_payments=mandatory,
                black_day_fund=black_day,
                wishlist_name=wishlist_name or "Хотелка",
                wishlist_target=wishlist_price,
                period_start_day=period_start_day
            )
            session.add(budget)

        await session.commit()


async def update_budget_field(telegram_id: int, field: str, value):
    month = datetime.now().strftime("%Y-%m")
    async with async_session_maker() as session:
        result = await session.execute(
            select(Budget).where(
                Budget.telegram_id == telegram_id,
                Budget.month == month
            )
        )
        budget = result.scalar_one_or_none()
        if budget:
            setattr(budget, field, value)
            await session.commit()


async def delete_current_budget(telegram_id: int):
    month = datetime.now().strftime("%Y-%m")
    async with async_session_maker() as session:
        result = await session.execute(
            select(Budget).where(
                Budget.telegram_id == telegram_id,
                Budget.month == month
            )
        )
        budget = result.scalar_one_or_none()
        if budget:
            await session.delete(budget)
            await session.commit()


async def get_days_remaining(telegram_id: int) -> int:
    month = datetime.now().strftime("%Y-%m")
    async with async_session_maker() as session:
        result = await session.execute(
            select(Budget).where(
                Budget.telegram_id == telegram_id,
                Budget.month == month,
            )
        )
        budget = result.scalar_one_or_none()
        if not budget:
            return 1
        return budget.days_remaining


async def reconcile_budget_with_reality(telegram_id: int, real_cash: float) -> float:
    month = datetime.now().strftime("%Y-%m")
    async with async_session_maker() as session:
        result = await session.execute(
            select(Budget).where(
                Budget.telegram_id == telegram_id,
                Budget.month == month,
            )
        )
        budget = result.scalar_one_or_none()
        if not budget:
            return 0.0

        budget.total_income = real_cash
        days_left = budget.days_remaining
        if days_left <= 0:
            days_left = 1

        new_daily_limit = max(real_cash / days_left, 0)
        await session.commit()
        return new_daily_limit
