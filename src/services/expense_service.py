from datetime import date, datetime, time

from sqlalchemy import func, select

from ..db.database import async_session_maker
from ..db.models.models import Expense, UserSettings
from ..utils import phrases

PAGE_SIZE = 5
IGNORE_WORDS = {"рублей", "рубля", "рубль", "руб", "₽"}


async def try_apply_round_up(telegram_id: int, amount: float) -> str | None:
    import math

    async with async_session_maker() as session:
        result = await session.execute(
            select(UserSettings).where(UserSettings.telegram_id == telegram_id)
        )
        settings = result.scalar_one_or_none()
        if not settings or settings.rounding_mode <= 0:
            return None

        mode = settings.rounding_mode
        rounded = math.ceil(amount / mode) * mode
        spare = rounded - amount
        if spare <= 0:
            return None

    from .goal_service import add_spare_change_to_goal
    new_total, goal_name = await add_spare_change_to_goal(telegram_id, spare)

    return phrases.ROUND_UP.format(amount=int(spare), goal=goal_name, total=int(new_total))


def clean_description(text: str) -> str:
    import re
    pattern = r'\b(' + '|'.join(re.escape(w) for w in IGNORE_WORDS) + r')\b'
    text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    text = re.sub(r'\bр\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'[\s\+]+', ' ', text).strip()
    return text[:500]


def parse_expense_text(text: str) -> tuple[float, str] | None:
    import re
    numbers = re.findall(r'\d+(?:[,\.]\d+)?', text)
    total = 0.0
    first_num = None
    for num_str in numbers:
        try:
            amount = float(num_str.replace(",", "."))
            if amount > 0:
                if first_num is None:
                    first_num = num_str
                    total = amount
                break
        except (ValueError, TypeError):
            continue

    if total <= 0:
        return None

    description = text
    if first_num:
        description = description.replace(first_num, "", 1)
    description = clean_description(description)

    return total, description


def parse_multi_expense_text(text: str) -> list[tuple[float, str]]:
    lines = text.strip().split("\n")
    results = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        parsed = parse_expense_text(line)
        if parsed:
            results.append(parsed)
    return results


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


async def get_today_expenses_sum(telegram_id: int) -> float:
    today_start = datetime.combine(date.today(), time.min)
    today_end = datetime.combine(date.today(), time.max)

    async with async_session_maker() as session:
        result = await session.execute(
            select(func.sum(Expense.amount))
            .where(Expense.telegram_id == telegram_id)
            .where(Expense.date >= today_start)
            .where(Expense.date <= today_end)
            .where(Expense.is_deleted == False)
        )
        total = result.scalar()
        return float(total) if total else 0.0


async def get_today_daily_limit(telegram_id: int) -> float:
    from .budget_service import get_active_budget
    budget = await get_active_budget(telegram_id)
    if not budget:
        return 0.0
    return budget.daily_limit


async def get_current_period_expenses_sum(telegram_id: int) -> float:
    import calendar
    from datetime import timedelta

    from .budget_service import get_active_budget

    budget = await get_active_budget(telegram_id)
    if not budget:
        return 0.0

    today = datetime.now()
    start_day = budget.period_start_day or 1
    clamped = min(start_day, calendar.monthrange(today.year, today.month)[1])

    if clamped == 1:
        period_start = datetime(today.year, today.month, 1)
        next_month = today.replace(day=1) + timedelta(days=32)
        period_end = datetime(next_month.year, next_month.month, 1) - timedelta(seconds=1)
    elif today.day >= clamped:
        period_start = datetime(today.year, today.month, clamped)
        next_month = today.replace(day=1) + timedelta(days=32)
        period_end = datetime(next_month.year, next_month.month, clamped - 1, 23, 59, 59)
    else:
        last_month = datetime(today.year, today.month, 1) - timedelta(days=1)
        period_start = datetime(last_month.year, last_month.month, clamped)
        period_end = datetime(today.year, today.month, clamped - 1, 23, 59, 59)

    async with async_session_maker() as session:
        result = await session.execute(
            select(func.sum(Expense.amount))
            .where(Expense.telegram_id == telegram_id)
            .where(Expense.date >= period_start)
            .where(Expense.date <= period_end)
            .where(Expense.is_deleted == False)
        )
        total = result.scalar()
        return float(total) if total else 0.0


async def get_yesterday_expenses_sum(telegram_id: int) -> float:
    from datetime import timedelta
    yesterday = date.today() - timedelta(days=1)
    day_start = datetime.combine(yesterday, time.min)
    day_end = datetime.combine(yesterday, time.max)

    async with async_session_maker() as session:
        result = await session.execute(
            select(func.sum(Expense.amount))
            .where(Expense.telegram_id == telegram_id)
            .where(Expense.date >= day_start)
            .where(Expense.date <= day_end)
            .where(Expense.is_deleted == False)
        )
        total = result.scalar()
        return float(total) if total else 0.0
