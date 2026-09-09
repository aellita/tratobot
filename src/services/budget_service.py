from datetime import timedelta

from sqlalchemy import select

from ..db.database import async_session_maker
from ..db.models.models import Budget
from ..utils import phrases
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


async def _compute_base_limit(
    income: float, mandatory: float, black_day: float, period_start_day: int
) -> float:
    import calendar

    from ..utils.helpers import get_msk_now

    today = get_msk_now()
    start = min(period_start_day or 1, calendar.monthrange(today.year, today.month)[1])
    if start == 1:
        total = calendar.monthrange(today.year, today.month)[1]
    else:
        total = 30
    available = max(income - mandatory - black_day, 0)
    return max(available / max(total, 1), 0)


async def resolve_frozen_baseline(budget: Budget) -> float:
    if budget.base_daily_limit is not None:
        return budget.base_daily_limit
    b = float(budget.daily_limit)
    async with async_session_maker() as session:
        result = await session.execute(select(Budget).where(Budget.id == budget.id))
        fresh = result.scalar_one_or_none()
        if fresh and fresh.base_daily_limit is None:
            fresh.base_daily_limit = b
            await session.commit()
            return b
        if fresh and fresh.base_daily_limit is not None:
            return fresh.base_daily_limit
    return b


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
    base_limit = await _compute_base_limit(income, mandatory, black_day, period_start_day)
    async with async_session_maker() as session:
        result = await session.execute(
            select(Budget).where(Budget.telegram_id == telegram_id, Budget.month == month)
        )
        budget = result.scalar_one_or_none()

        if budget:
            budget.total_income = income
            budget.mandatory_payments = mandatory
            budget.black_day_fund = black_day
            budget.wishlist_name = wishlist_name or phrases.DEFAULT_WISHLIST_NAME
            budget.wishlist_target = wishlist_price
            budget.period_start_day = period_start_day
            budget.free_money = free_money
            budget.base_daily_limit = base_limit
        else:
            budget = Budget(
                telegram_id=telegram_id,
                month=month,
                total_income=income,
                mandatory_payments=mandatory,
                black_day_fund=black_day,
                wishlist_name=wishlist_name or phrases.DEFAULT_WISHLIST_NAME,
                wishlist_target=wishlist_price,
                period_start_day=period_start_day,
                free_money=free_money,
                spent_at_recalc=0,
                base_daily_limit=base_limit,
            )
            session.add(budget)

        await session.commit()


ALLOWED_FIELDS = {
    "total_income",
    "mandatory_payments",
    "black_day_fund",
    "free_money",
    "spent_at_recalc",
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


def get_money_for_life(budget: Budget, spent_period: float) -> float:
    if budget.free_money > 0:
        spent_at = float(budget.spent_at_recalc or 0)
        new_spent = max(spent_period - spent_at, 0)
        return max(float(budget.free_money) - new_spent, 0)
    return max(
        float(budget.total_income) - float(budget.mandatory_payments) - float(spent_period),
        0,
    )


def _current_money_for_life(budget: Budget, spent_period: float) -> float:
    return get_money_for_life(budget, spent_period)


def get_daily_pred(money_for_life: float, days_left: int) -> float:
    if money_for_life <= 0 or days_left <= 0:
        return 0
    return max(money_for_life / max(days_left, 1), 0)


async def get_period_spent(telegram_id: int, budget: Budget) -> float:
    from sqlalchemy import func as _func

    from ..db.models.models import Expense as _Expense
    from ..services.monthly_report import get_period_dates as _get_period_dates

    period_start, period_end = _get_period_dates(budget)
    next_day = period_end + timedelta(days=1)
    async with async_session_maker() as session:
        result = await session.execute(
            select(_func.sum(_Expense.amount)).where(
                _Expense.telegram_id == telegram_id,
                _Expense.is_deleted == False,
                _Expense.date >= period_start,
                _Expense.date < next_day,
            )
        )
        return float(result.scalar() or 0)


async def apply_reconciliation(
    telegram_id: int,
    free_money: float,
    new_mandatory: float | None = None,
    new_black_day: float | None = None,
) -> None:
    from sqlalchemy import func as _func

    from ..services.monthly_report import get_period_dates as _get_period_dates

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
        # snapshot spent_at_recalc atomically with free_money
        period_start, period_end = _get_period_dates(budget)
        next_day = period_end + timedelta(days=1)
        from ..db.models.models import Expense as _Expense

        spent_res = await session.execute(
            select(_func.sum(_Expense.amount)).where(
                _Expense.telegram_id == telegram_id,
                _Expense.is_deleted == False,
                _Expense.date >= period_start,
                _Expense.date < next_day,
            )
        )
        spent_at = float(spent_res.scalar() or 0)
        budget.free_money = free_money
        budget.spent_at_recalc = spent_at
        if new_mandatory is not None:
            budget.mandatory_payments = new_mandatory
        if new_black_day is not None:
            budget.black_day_fund = new_black_day
        await session.commit()
