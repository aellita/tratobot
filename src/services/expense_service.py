import math
import re
from dataclasses import dataclass, field
from datetime import datetime, time

from sqlalchemy import func, select

from ..db.database import async_session_maker
from ..db.models.models import Expense, UserSettings
from ..utils import phrases
from ..utils.helpers import (
    _parse_math_prefix,
    _preprocess_math,
    _split_math_prefix,
    get_msk_now,
    safe,
)

PAGE_SIZE = 5
IGNORE_WORDS = {"рублей", "рубля", "рубль", "руб", "₽"}


@dataclass
class ExpenseParseReport:
    amount: float = 0.0
    description: str = ""
    is_valid: bool = False
    raw_text: str = ""
    line_number: int = 0
    error_type: str | None = None
    error_detail: str | None = None
    was_corrected: bool = False
    correction_hint: str | None = None


@dataclass
class MultiExpenseParseResult:
    reports: list[ExpenseParseReport] = field(default_factory=list)
    is_fully_valid: bool = False


def _detect_math_error(text: str) -> str:
    if re.search(r"/\s*0(?:\D|$)", text):
        return phrases.ERR_DIV_BY_ZERO
    parts = _split_math_prefix(text)
    if parts and re.search(r"[+\-*/]+\s*$", parts[0]):
        return phrases.ERR_MISSING_NUMBER
    return phrases.ERR_CANNOT_PARSE


def compute_rounding(amount: float, mode: int) -> tuple[float, float]:
    rounded = math.ceil(amount / mode) * mode
    spare = rounded - amount
    return rounded, spare


async def get_rounding_mode(telegram_id: int) -> int:
    async with async_session_maker() as session:
        result = await session.execute(
            select(UserSettings).where(UserSettings.telegram_id == telegram_id)
        )
        settings = result.scalar_one_or_none()
        return settings.rounding_mode if settings else 0


def clean_description(text: str) -> str:
    pattern = r"\b(" + "|".join(re.escape(w) for w in IGNORE_WORDS) + r")\b"
    text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bр\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[\s\+]+", " ", text).strip()
    return text[:500]


def _fallback_first_number(text: str) -> ExpenseParseReport | None:
    """Try to extract first number as amount. Returns report or None if no numbers."""
    numbers = re.findall(r"\d+(?:[,\.]\d+)?(?:[eE][+-]?\d+)?", text)
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
    return ExpenseParseReport(
        amount=total,
        description=clean_description(description),
        is_valid=True,
        raw_text=text,
    )


def parse_expense_text(text: str, line_number: int = 0) -> ExpenseParseReport:
    if not text.strip():
        return ExpenseParseReport(raw_text=text, line_number=line_number, error_type="EMPTY")

    has_math = bool(re.search(r"[+\-*/()]", text))

    math_result = _parse_math_prefix(text)
    if math_result is not None:
        total, rest = math_result
        if total > 0:
            if not re.search(r"[+\-*/]\s*\d", rest):
                raw_rest = rest
                rest = re.sub(r"\s*[+\-*/()]+\s*", " ", rest).strip()
                was_corrected = rest != raw_rest.strip()
                return ExpenseParseReport(
                    amount=total,
                    description=clean_description(rest),
                    is_valid=True,
                    raw_text=text,
                    line_number=line_number,
                    was_corrected=was_corrected,
                    correction_hint=phrases.HINT_JUNK_CHARS if was_corrected else None,
                )
            has_math = True
        else:
            err_detail = (
                phrases.ERR_ZERO_RESULT
                if total == 0
                else phrases.ERR_NEGATIVE_RESULT.format(total=total)
            )
            return ExpenseParseReport(
                raw_text=text,
                line_number=line_number,
                error_type="MATH_ERROR",
                error_detail=err_detail,
            )

    if has_math:
        fixed, was_corrected, hint = _preprocess_math(text)
        if was_corrected:
            math_result = _parse_math_prefix(fixed)
            if math_result is not None:
                total, rest = math_result
                if total > 0:
                    return ExpenseParseReport(
                        amount=total,
                        description=clean_description(rest),
                        is_valid=True,
                        raw_text=text,
                        line_number=line_number,
                        was_corrected=True,
                        correction_hint=hint,
                    )
                err_detail = (
                    phrases.ERR_ZERO_RESULT
                    if total == 0
                    else phrases.ERR_NEGATIVE_RESULT.format(total=total)
                )
                return ExpenseParseReport(
                    raw_text=text,
                    line_number=line_number,
                    error_type="MATH_ERROR",
                    error_detail=err_detail,
                )
            fallback = _fallback_first_number(fixed)
            if fallback is not None:
                fallback.line_number = line_number
                fallback.was_corrected = True
                fallback.correction_hint = hint
                return fallback
        return ExpenseParseReport(
            raw_text=text,
            line_number=line_number,
            error_type="MATH_ERROR",
            error_detail=_detect_math_error(text),
        )

    fallback = _fallback_first_number(text)
    if fallback is not None:
        fallback.line_number = line_number
        return fallback

    return ExpenseParseReport(raw_text=text, line_number=line_number, error_type="NO_NUMBER")


def parse_multi_expense_text(text: str) -> MultiExpenseParseResult:
    lines = text.strip().split("\n")
    reports = []
    for i, line in enumerate(lines):
        line = line.strip()
        if not line or not re.search(r"\d", line):
            continue
        reports.append(parse_expense_text(line, line_number=i + 1))
    is_fully_valid = all(r.is_valid for r in reports)
    return MultiExpenseParseResult(reports=reports, is_fully_valid=is_fully_valid)


async def get_expense_page(telegram_id: int, page: int = 0) -> tuple[list[Expense], int, int]:
    async with async_session_maker() as session:
        total_q = await session.execute(
            select(func.count(Expense.id)).where(
                Expense.telegram_id == telegram_id, Expense.is_deleted == False
            )
        )
        total = total_q.scalar() or 0

        result = await session.execute(
            select(Expense)
            .where(Expense.telegram_id == telegram_id, Expense.is_deleted == False)
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
                Expense.is_deleted == False,
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
                Expense.is_deleted == True,
            )
        )
        expense = result.scalar_one_or_none()
        if not expense:
            return None

        expense.is_deleted = False
        await session.commit()
        return expense


async def update_expense_amount(
    telegram_id: int, expense_id: int, new_amount: float
) -> Expense | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Expense).where(
                Expense.id == expense_id,
                Expense.telegram_id == telegram_id,
                Expense.is_deleted == False,
            )
        )
        expense = result.scalar_one_or_none()
        if not expense:
            return None

        expense.amount = new_amount
        await session.commit()
        return expense


async def get_today_expenses_sum(telegram_id: int) -> float:
    today_msk = get_msk_now().date()
    today_start = datetime.combine(today_msk, time.min)
    today_end = datetime.combine(today_msk, time.max)

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


async def get_today_expenses_grouped(telegram_id: int) -> list[str]:
    from ..db.models.models import Category
    from .categorization import get_category_display

    today = get_msk_now().date()
    day_start = datetime.combine(today, time.min)
    day_end = datetime.combine(today, time.max)

    async with async_session_maker() as session:
        result = await session.execute(
            select(Expense, Category)
            .outerjoin(Category, Expense.category_id == Category.id)
            .where(Expense.telegram_id == telegram_id)
            .where(Expense.date >= day_start)
            .where(Expense.date <= day_end)
            .where(Expense.is_deleted == False)
            .order_by(Expense.date)
        )
        rows = result.all()

    lines: list[str] = []
    for exp, cat in rows:
        if cat:
            emoji, cat_name = get_category_display(cat.name)
            if (exp.description or "").strip().lower() == cat_name.lower():
                prefix = emoji
            else:
                prefix = f"{emoji} {safe(cat_name)}"
        else:
            prefix = "📦 Прочее"
        desc = safe(exp.description or "")
        label = f"{desc} — {exp.amount:,.0f}₽" if desc else f"{exp.amount:,.0f}₽"
        lines.append(f"{prefix} {label}")

    return lines


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

    today = get_msk_now()
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

    yesterday = get_msk_now().date() - timedelta(days=1)
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
