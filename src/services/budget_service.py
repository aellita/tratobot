from datetime import timedelta

from sqlalchemy import select

from ..db.database import async_session_maker
from ..db.models.models import Budget
from ..utils.helpers import get_msk_now


async def get_active_budget(telegram_id: int) -> Budget | None:
    today = get_msk_now()
    this_month = today.strftime("%Y-%m")
    last_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

    async with async_session_maker() as session:
        result = await session.execute(
            select(Budget)
            .where(
                Budget.telegram_id == telegram_id,
                Budget.month.in_([this_month, last_month]),
            )
            .order_by(Budget.month.desc())
        )
        budgets = result.scalars().all()

    for budget in budgets:
        start = budget.period_start_day or 1
        if today.day >= start and budget.month == this_month:
            return budget
        if today.day < start and budget.month == last_month:
            return budget

    return None


async def save_budget(
    telegram_id: int,
    month: str,
    income: float,
    mandatory: float,
    black_day: float,
    wishlist_name: str = None,
    wishlist_price: float = 0,
    period_start_day: int = 1,
    free_money: float = 0,
):
    async with async_session_maker() as session:
        result = await session.execute(
            select(Budget).where(Budget.telegram_id == telegram_id, Budget.month == month)
        )
        budget = result.scalar_one_or_none()

        if budget:
            budget.total_income = income
            budget.mandatory_payments = mandatory
            budget.black_day_fund = black_day
            budget.wishlist_name = wishlist_name or "Хотелка"
            budget.wishlist_target = wishlist_price
            budget.period_start_day = period_start_day
            budget.free_money = free_money
        else:
            budget = Budget(
                telegram_id=telegram_id,
                month=month,
                total_income=income,
                mandatory_payments=mandatory,
                black_day_fund=black_day,
                wishlist_name=wishlist_name or "Хотелка",
                wishlist_target=wishlist_price,
                period_start_day=period_start_day,
                free_money=free_money,
            )
            session.add(budget)

        await session.commit()


ALLOWED_FIELDS = {
    "total_income",
    "mandatory_payments",
    "black_day_fund",
    "free_money",
    "wishlist_name",
    "wishlist_target",
    "period_start_day",
}


async def update_budget_field(telegram_id: int, field: str, value):
    if field not in ALLOWED_FIELDS:
        raise ValueError(f"Invalid budget field: {field}")
    month = get_msk_now().strftime("%Y-%m")
    async with async_session_maker() as session:
        result = await session.execute(
            select(Budget).where(Budget.telegram_id == telegram_id, Budget.month == month)
        )
        budget = result.scalar_one_or_none()
        if budget:
            setattr(budget, field, value)
            await session.commit()


async def delete_current_budget(telegram_id: int):
    month = get_msk_now().strftime("%Y-%m")
    async with async_session_maker() as session:
        result = await session.execute(
            select(Budget).where(Budget.telegram_id == telegram_id, Budget.month == month)
        )
        budget = result.scalar_one_or_none()
        if budget:
            await session.delete(budget)
            await session.commit()


async def get_days_remaining(telegram_id: int) -> int:
    month = get_msk_now().strftime("%Y-%m")
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


async def reconcile_budget_with_reality(
    telegram_id: int, total_balance: float
) -> tuple[float, int, float, float, float]:
    budget = await get_active_budget(telegram_id)
    if not budget:
        return 0.0, 1, 0.0, 0.0, 0.0

    money_for_life = max(total_balance, 0)
    days_left = budget.days_remaining
    if days_left <= 0:
        days_left = 1

    new_daily_limit = max(money_for_life / days_left, 0)
    return (
        new_daily_limit,
        days_left,
        money_for_life,
        budget.mandatory_payments,
        budget.black_day_fund,
    )


async def apply_reconciliation(
    telegram_id: int,
    free_money: float,
    new_mandatory: float | None = None,
    new_black_day: float | None = None,
) -> None:
    today = get_msk_now()
    this_month = today.strftime("%Y-%m")
    last_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    async with async_session_maker() as session:
        result = await session.execute(
            select(Budget)
            .where(
                Budget.telegram_id == telegram_id,
                Budget.month.in_([this_month, last_month]),
            )
            .order_by(Budget.month.desc())
        )
        budgets = result.scalars().all()
        budget = None
        for b in budgets:
            start = b.period_start_day or 1
            if today.day >= start and b.month == this_month:
                budget = b
                break
            if today.day < start and b.month == last_month:
                budget = b
                break
        if not budget:
            return
        budget.free_money = free_money
        if new_mandatory is not None:
            budget.mandatory_payments = new_mandatory
        if new_black_day is not None:
            budget.black_day_fund = new_black_day
        await session.commit()
