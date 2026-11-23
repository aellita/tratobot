from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select

from ..db.database import async_session_maker
from ..db.models.models import Budget, DailyLimit, RecoveryState
from ..utils import phrases
from ..utils.helpers import get_msk_now


class NoActiveBudgetError(LookupError):
    """У пользователя нет активного бюджета на текущий период."""


@dataclass(frozen=True)
class TodayPlan:
    """Canonical today's plan shared by status, morning report and snapshots."""

    plan_today: float
    spent_today: float
    spent_period: float
    days_left: int
    base_limit: float
    money_for_life: float
    money_for_life_raw: float


def month_for_period_start(start_day: int, today: datetime | None = None) -> str:
    """Месяц, в котором начался период с указанным днём старта."""
    today = today or get_msk_now()
    if today.day >= start_day:
        return today.strftime("%Y-%m")
    return (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")


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
    income: float,
    mandatory: float,
    black_day: float,
    period_start_day: int,
    month: str,
) -> float:
    from ..utils.helpers import period_total_days

    total = period_total_days(month, period_start_day or 1)
    available = max(income - mandatory - black_day, 0)
    return max(available / max(total, 1), 0)


async def get_base_daily_limit(budget: Budget) -> float:
    """Базовый лимит периода: (доход − обязательные − кубышка) / дни периода."""
    if budget.base_daily_limit is not None and budget.base_daily_limit > 0:
        return float(budget.base_daily_limit)
    return await _compute_base_limit(
        budget.total_income,
        budget.mandatory_payments,
        budget.black_day_fund,
        budget.period_start_day or 1,
        budget.month,
    )


async def resolve_frozen_baseline(budget: Budget) -> float:
    if budget.base_daily_limit is not None:
        return budget.base_daily_limit
    # база периода — от дохода, а не от остатка на карте (иначе она «дышит»)
    b = await _compute_base_limit(
        budget.total_income,
        budget.mandatory_payments,
        budget.black_day_fund,
        budget.period_start_day or 1,
        budget.month,
    )
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
    base_limit = await _compute_base_limit(income, mandatory, black_day, period_start_day, month)
    async with async_session_maker() as session:
        result = await session.execute(
            select(Budget).where(Budget.telegram_id == telegram_id, Budget.month == month)
        )
        budget = result.scalar_one_or_none()

        if budget:
            budget.total_income = income
            budget.added_income = 0
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
                added_income=0,
                mandatory_payments=mandatory,
                black_day_fund=black_day,
                wishlist_name=wishlist_name or phrases.DEFAULT_WISHLIST_NAME,
                wishlist_target=wishlist_price,
                period_start_day=period_start_day,
                free_money=free_money,
                spent_at_recalc=0,
                spent_today_at_recalc=0,
                recalc_date=None,
                base_daily_limit=base_limit,
            )
            session.add(budget)

        await session.commit()

    from .daily_limits import refresh_daily_limit

    await refresh_daily_limit(telegram_id)


async def add_income(telegram_id: int, amount: float) -> Budget:
    """Добавить доход в активный период и запомнить сумму добавки."""
    active = await get_active_budget(telegram_id)
    if not active:
        raise NoActiveBudgetError(f"No active budget for {telegram_id}")

    async with async_session_maker() as session:
        budget = await session.get(Budget, active.id)
        if budget is None:
            raise NoActiveBudgetError(f"No active budget for {telegram_id}")

        if float(budget.free_money or 0) > 0:
            budget.free_money = float(budget.free_money) + amount
        else:
            budget.total_income = float(budget.total_income) + amount
            budget.base_daily_limit = await _compute_base_limit(
                budget.total_income,
                budget.mandatory_payments,
                budget.black_day_fund,
                budget.period_start_day or 1,
                budget.month,
            )
        budget.added_income = float(budget.added_income or 0) + amount

        await session.commit()
        await session.refresh(budget)

    from .daily_limits import refresh_daily_limit

    await refresh_daily_limit(telegram_id)
    return budget


ALLOWED_FIELDS = {
    "total_income",
    "mandatory_payments",
    "black_day_fund",
    "free_money",
    "spent_at_recalc",
    "spent_today_at_recalc",
    "recalc_date",
    "wishlist_name",
    "wishlist_target",
    "period_start_day",
}

_BASE_LIMIT_FIELDS = {
    "total_income",
    "mandatory_payments",
    "black_day_fund",
    "period_start_day",
}


async def _delete_budget_row(session, budget: Budget) -> None:
    """Удалить бюджет вместе с recovery-состояниями.

    ``RecoveryState.budget_id`` — обычный FK без cascade, поэтому на PostgreSQL
    удаление бюджета с историей Recovery упадёт с IntegrityError.
    """
    await session.execute(delete(RecoveryState).where(RecoveryState.budget_id == budget.id))
    await session.delete(budget)


async def update_budget_field(telegram_id: int, field: str, value) -> Budget:
    """Обновить поле активного бюджета.

    Правка всегда идёт в бюджет, который реально активен сейчас, а не в
    календарный текущий месяц: при ``period_start_day`` больше сегодняшнего
    числа активным может быть бюджет прошлого месяца.

    Raises:
        NoActiveBudgetError: если активного бюджета нет.
    """
    if field not in ALLOWED_FIELDS:
        raise ValueError(f"Invalid budget field: {field}")

    active = await get_active_budget(telegram_id)
    if not active:
        raise NoActiveBudgetError(f"No active budget for {telegram_id}")

    async with async_session_maker() as session:
        budget = await session.get(Budget, active.id)
        if budget is None:
            raise NoActiveBudgetError(f"No active budget for {telegram_id}")

        setattr(budget, field, value)

        if field == "period_start_day":
            target_month = month_for_period_start(int(value))
            if target_month != budget.month:
                # Активный бюджет — источник правды. Если в целевом месяце
                # осталась строка от старого онбординг-бага, заменяем её.
                conflict = await session.execute(
                    select(Budget).where(
                        Budget.telegram_id == telegram_id,
                        Budget.month == target_month,
                    )
                )
                stale = conflict.scalar_one_or_none()
                if stale is not None and stale.id != budget.id:
                    await _delete_budget_row(session, stale)
                budget.month = target_month

        if field in _BASE_LIMIT_FIELDS:
            budget.base_daily_limit = await _compute_base_limit(
                budget.total_income,
                budget.mandatory_payments,
                budget.black_day_fund,
                budget.period_start_day or 1,
                budget.month,
            )

        await session.commit()
        await session.refresh(budget)

    from .daily_limits import refresh_daily_limit

    await refresh_daily_limit(telegram_id)
    return budget


async def delete_active_budget(telegram_id: int) -> bool:
    """Удалить активный бюджет. Возвращает False, если удалять нечего."""
    active = await get_active_budget(telegram_id)
    if not active:
        return False
    async with async_session_maker() as session:
        budget = await session.get(Budget, active.id)
        if budget is None:
            return False
        from .monthly_report import get_period_dates

        period_start, period_end = get_period_dates(budget)
        await session.execute(
            delete(DailyLimit).where(
                DailyLimit.telegram_id == telegram_id,
                DailyLimit.plan_date >= period_start.date(),
                DailyLimit.plan_date <= period_end.date(),
            )
        )
        await _delete_budget_row(session, budget)
        await session.commit()
        return True


async def delete_all_budgets(telegram_id: int) -> int:
    """Удалить все бюджеты пользователя. Возвращает число удалённых."""
    async with async_session_maker() as session:
        result = await session.execute(select(Budget).where(Budget.telegram_id == telegram_id))
        budgets = result.scalars().all()
        for budget in budgets:
            await _delete_budget_row(session, budget)
        await session.execute(delete(DailyLimit).where(DailyLimit.telegram_id == telegram_id))
        await session.commit()
        return len(budgets)


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


def get_money_for_life_raw(budget: Budget, spent_period: float) -> float:
    """Остаток без клампа в 0 — нужен для честного плана на сегодня."""
    if budget.free_money > 0:
        spent_at = float(budget.spent_at_recalc or 0)
        new_spent = max(spent_period - spent_at, 0)
        return float(budget.free_money) - new_spent
    return float(budget.total_income) - float(budget.mandatory_payments) - float(spent_period)


def get_money_for_life(budget: Budget, spent_period: float) -> float:
    return max(get_money_for_life_raw(budget, spent_period), 0)


def get_spent_today_at_recalc(budget: Budget) -> float:
    """Сколько было потрачено сегодня на момент последнего пересчёта.

    Снапшот действует только в день пересчёта: на следующий день его нельзя
    вычитать, иначе новые траты «съедят» план.
    """
    if budget.recalc_date is None:
        return 0.0
    if budget.recalc_date != get_msk_now().date():
        return 0.0
    return float(budget.spent_today_at_recalc or 0)


def _current_money_for_life(budget: Budget, spent_period: float) -> float:
    return get_money_for_life(budget, spent_period)


def get_daily_pred(money_for_life: float, days_left: int) -> float:
    if money_for_life <= 0 or days_left <= 0:
        return 0
    return max(money_for_life / max(days_left, 1), 0)


def get_plan_today(
    money_for_life_raw: float,
    spent_today: float,
    days_left: int,
    spent_today_at_recalc: float = 0,
) -> float:
    """Утренний план на сегодня — фиксированный в течение дня.

    ``money_for_life_raw`` — остаток **до** клампа в 0: если период уже
    перерасходован, план не должен расти от сегодняшних трат.

    ``spent_today_at_recalc`` — сегодняшние траты на момент пересчёта
    остатка на карте. Добавляем обратно только то, что потрачено **после**
    пересчёта, чтобы план не прыгал от уже учтённых трат.
    """
    if days_left <= 0:
        return 0
    spent_after_recalc = max(spent_today - spent_today_at_recalc, 0)
    return max((money_for_life_raw + spent_after_recalc) / max(days_left, 1), 0)


def get_free_today(plan_today: float, spent_today: float) -> float:
    return max(plan_today - spent_today, 0)


def get_overrun_today(plan_today: float, spent_today: float) -> float:
    return max(spent_today - plan_today, 0)


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


async def compute_today_plan(telegram_id: int, budget: Budget) -> TodayPlan:
    """Single source of truth for today's plan and its inputs."""
    from .expense_service import get_today_expenses_sum

    spent_period = await get_period_spent(telegram_id, budget)
    spent_today = await get_today_expenses_sum(telegram_id)
    money_for_life_raw = get_money_for_life_raw(budget, spent_period)
    days_left = budget.days_remaining
    return TodayPlan(
        plan_today=get_plan_today(
            money_for_life_raw,
            spent_today,
            days_left,
            get_spent_today_at_recalc(budget),
        ),
        spent_today=spent_today,
        spent_period=spent_period,
        days_left=days_left,
        base_limit=await get_base_daily_limit(budget),
        money_for_life=get_money_for_life(budget, spent_period),
        money_for_life_raw=money_for_life_raw,
    )


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
        today_start = today.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        spent_today_res = await session.execute(
            select(_func.sum(_Expense.amount)).where(
                _Expense.telegram_id == telegram_id,
                _Expense.is_deleted == False,
                _Expense.date >= today_start,
                _Expense.date < today_end,
            )
        )
        spent_today_at = float(spent_today_res.scalar() or 0)
        budget.free_money = free_money
        budget.spent_at_recalc = spent_at
        budget.spent_today_at_recalc = spent_today_at
        budget.recalc_date = today.date()
        if new_mandatory is not None:
            budget.mandatory_payments = new_mandatory
        if new_black_day is not None:
            budget.black_day_fund = new_black_day
        await session.commit()

    from .daily_limits import refresh_daily_limit

    await refresh_daily_limit(telegram_id)
