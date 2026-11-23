"""Monthly chart: PNG card rendering (Financial Bro style) + Widget state/HTML."""

import functools
import json
import logging
import statistics
import zlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import NotRequired, TypedDict

from sqlalchemy import func, select

from ..db.database import async_session_maker
from ..db.models.models import Budget, Category, Expense
from ..utils.helpers import get_msk_now, period_dates, period_total_days

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Widget state / HTML (kept for fallback compatibility)
# ──────────────────────────────────────────────────────────────────────


class ChartDayData(TypedDict):
    spent: float


class ChartState(TypedDict):
    m: str
    s: str
    d: list[float]
    lim: float
    a: bool


def _compute_base_daily_limit(budget: Budget) -> float:
    if budget.base_daily_limit is not None and budget.base_daily_limit > 0:
        return float(budget.base_daily_limit)
    available = (
        float(budget.total_income) - float(budget.mandatory_payments) - float(budget.black_day_fund)
    )
    if available <= 0:
        return 0.0
    total_days = period_total_days(budget.month, budget.period_start_day or 1)
    return max(available / max(total_days, 1), 0.0)


def _chart_window(budget: Budget) -> tuple[datetime, date, bool]:
    period_start, period_end = period_dates(budget.month, budget.period_start_day or 1)
    today = get_msk_now().date()
    start_date = period_start.date()
    end_of_period = period_end.date()

    if today < start_date:
        return period_start, start_date - timedelta(days=1), False

    active = start_date <= today <= end_of_period
    end_date = min(end_of_period, today) if active else end_of_period
    return period_start, end_date, active


async def build_chart_data(telegram_id: int, budget: Budget) -> list[ChartDayData]:
    period_start, end_date, _ = _chart_window(budget)
    if end_date < period_start.date():
        return []

    next_day_start = datetime.combine(end_date + timedelta(days=1), datetime.min.time())

    async with async_session_maker() as session:
        result = await session.execute(
            select(
                func.date(Expense.date).label("expense_date"),
                func.sum(Expense.amount).label("total_spent"),
            )
            .where(Expense.telegram_id == telegram_id)
            .where(Expense.date >= period_start)
            .where(Expense.date < next_day_start)
            .where(Expense.is_deleted == False)
            .group_by(func.date(Expense.date))
        )
        rows = result.all()

    spent_by_date: dict[str, float] = {
        str(row.expense_date): float(row.total_spent) for row in rows
    }

    data: list[ChartDayData] = []
    current = period_start.date()
    while current <= end_date:
        day_str = current.isoformat()
        data.append(ChartDayData(spent=spent_by_date.get(day_str, 0.0)))
        current += timedelta(days=1)

    return data


def build_chart_state(
    telegram_id: int,
    budget: Budget,
    data: list[ChartDayData],
    daily_limit: float | None = None,
) -> ChartState:
    _, _, is_active = _chart_window(budget)

    period_start, _ = period_dates(budget.month, budget.period_start_day or 1)
    period_start_str = period_start.strftime("%Y-%m-%d")

    month_prefix = budget.month
    spent_array = [round(d["spent"], 2) for d in data]
    base_limit = (
        float(daily_limit) if daily_limit is not None else _compute_base_daily_limit(budget)
    )

    state = ChartState(
        m=month_prefix,
        s=period_start_str,
        d=spent_array,
        lim=round(base_limit, 2),
        a=is_active,
    )

    json_str = json.dumps(state, separators=(",", ":"))
    if len(json_str.encode("utf-8")) > 1024:
        raise ValueError(f"Chart state exceeds 1024 bytes: {len(json_str)}")

    return state


# ──────────────────────────────────────────────────────────────────────
# PNG Card Rendering (Financial Bro style)
# ──────────────────────────────────────────────────────────────────────


class CardExpense(TypedDict):
    date: str
    amount: float
    category: NotRequired[str | None]


@dataclass
class MonthlyCardInput:
    period_start: date
    period_end: date
    period_start_day: int
    daily_spent: list[float]
    daily_limit: float
    total_spent: float
    expenses: list[CardExpense]
    expenses_count: int
    prev_expenses: list[CardExpense] | None = None
    prev_period_start: date | None = None
    prev_period_end: date | None = None
    current_income: float = 0.0
    prev_income: float = 0.0
    as_of: date | None = None
    is_active: bool = False
    upcoming: bool = False
    daily_limits: list[float] | None = None
    current_limit: float | None = None
    available_income: float | None = None


@dataclass(frozen=True)
class CardMetric:
    id: str
    title: str
    value: str
    subtitle: str
    bar: float = 0.0
    frog: str = ""


@dataclass(frozen=True)
class CardMetrics:
    state: str
    cards: tuple[CardMetric, ...]
    wide: CardMetric | None
    peak_callout: str | None
    current_limit: float
    limit_delta: float | None
    green: int
    tracked: int
    green_pct: int
    score: int | None
    league: str | None
    streak: int
    best_streak: int
    budget_saved: float | None
    chart_limits: tuple[float, ...]
    today_index: int | None


async def _fetch_card_expenses(
    telegram_id: int,
    start: datetime,
    end: datetime,
) -> list[CardExpense]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Expense.date, Expense.amount, Category.name)
            .outerjoin(Category, Expense.category_id == Category.id)
            .where(Expense.telegram_id == telegram_id)
            .where(Expense.date >= start)
            .where(Expense.date < end)
            .where(Expense.is_deleted == False)
        )
        return [
            CardExpense(
                date=expense_date.isoformat(),
                amount=float(amount),
                category=category_name,
            )
            for expense_date, amount, category_name in result.all()
        ]


async def build_monthly_card_input(
    telegram_id: int,
    budget: Budget,
    prev_budget: Budget | None = None,
    daily_limit: float | None = None,
) -> MonthlyCardInput:
    from .daily_limits import get_daily_limits, get_effective_daily_limit

    period_start, period_end = period_dates(budget.month, budget.period_start_day or 1)
    _, end_date, is_active = _chart_window(budget)
    today = get_msk_now().date()
    moving_limit = float(
        daily_limit if daily_limit is not None else _compute_base_daily_limit(budget)
    )
    chart_data = await build_chart_data(telegram_id, budget)
    daily_spent = [round(day["spent"], 2) for day in chart_data]

    snapshots = await get_daily_limits(
        telegram_id,
        period_start.date(),
        max(end_date, period_start.date()),
    )
    daily_limits = [
        float(snapshots.get(period_start.date() + timedelta(days=i), moving_limit))
        for i in range(len(daily_spent))
    ]

    current_limit = moving_limit
    if is_active:
        effective = await get_effective_daily_limit(telegram_id, budget)
        if effective is not None:
            current_limit = float(effective[0])

    next_day_start = datetime.combine(end_date + timedelta(days=1), datetime.min.time())
    expenses = await _fetch_card_expenses(telegram_id, period_start, next_day_start)

    prev_expenses = None
    prev_period_start = None
    prev_period_end = None
    prev_income = 0.0
    if prev_budget is not None:
        prev_start, prev_end = period_dates(prev_budget.month, prev_budget.period_start_day or 1)
        prev_days = max(len(daily_spent), 1)
        prev_cutoff = min(prev_start + timedelta(days=prev_days), prev_end + timedelta(days=1))
        prev_expenses = await _fetch_card_expenses(telegram_id, prev_start, prev_cutoff)
        prev_period_start = prev_start.date()
        prev_period_end = prev_end.date()
        prev_income = float((prev_budget.total_income or 0) + (prev_budget.added_income or 0))

    available_income = float(
        (budget.total_income or 0) - (budget.mandatory_payments or 0) - (budget.black_day_fund or 0)
    )

    return MonthlyCardInput(
        period_start=period_start.date(),
        period_end=period_end.date(),
        period_start_day=budget.period_start_day or 1,
        daily_spent=daily_spent,
        daily_limit=moving_limit,
        total_spent=round(sum(daily_spent), 2),
        expenses=expenses,
        expenses_count=len(expenses),
        prev_expenses=prev_expenses,
        prev_period_start=prev_period_start,
        prev_period_end=prev_period_end,
        current_income=float((budget.total_income or 0) + (budget.added_income or 0)),
        prev_income=prev_income,
        as_of=today,
        is_active=is_active,
        upcoming=today < period_start.date(),
        daily_limits=daily_limits,
        current_limit=current_limit,
        available_income=available_income,
    )


@functools.lru_cache(maxsize=32)
def _load_font(weight: str, size: int):
    from pathlib import Path

    from PIL import ImageFont

    font_dir = Path(__file__).resolve().parents[1] / "assets" / "fonts"
    font_path = font_dir / "Nunito-Variable.ttf"
    axis = {"regular": 400, "semibold": 600, "bold": 700}.get(weight, 400)
    if not font_path.exists():
        fallback_map = {
            "regular": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "semibold": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "bold": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        }
        font_path = Path(fallback_map.get(weight, fallback_map["regular"]))
    try:
        font = ImageFont.truetype(str(font_path), size)
        try:
            font.set_variation_by_axes([axis])
        except Exception:
            pass
        return font
    except Exception:
        logger.warning("Failed to load font %s, using Pillow default", font_path)
        return ImageFont.load_default()


def _format_rus_month(d: date) -> str:
    months = [
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ]
    return months[d.month - 1]


def _format_rus_period(start: date, end: date, start_day: int) -> str:
    if start_day == 1:
        months = [
            "январь",
            "февраль",
            "март",
            "апрель",
            "май",
            "июнь",
            "июль",
            "август",
            "сентябрь",
            "октябрь",
            "ноябрь",
            "декабрь",
        ]
        return f"{months[start.month - 1]} {start.year}"
    if start.year != end.year:
        return (
            f"{start.day} {_format_rus_month(start)} {start.year} — "
            f"{end.day} {_format_rus_month(end)} {end.year}"
        )
    return f"{start.day} {_format_rus_month(start)} — {end.day} {_format_rus_month(end)} {end.year}"


def _plural_ru(n: int, forms: tuple[str, str, str]) -> str:
    n = abs(n) % 100
    n1 = n % 10
    if 11 <= n <= 14:
        return forms[2]
    if n1 == 1:
        return forms[0]
    if 2 <= n1 <= 4:
        return forms[1]
    return forms[2]


def _date_str(value: date | datetime) -> str:
    return value.strftime("%Y-%m-%d")


def _expense_hour(expense: CardExpense) -> int | None:
    try:
        return datetime.fromisoformat(expense["date"]).hour
    except (TypeError, ValueError):
        return None


def _is_night_expense(expense: CardExpense) -> bool:
    hour = _expense_hour(expense)
    return hour is not None and (hour >= 21 or hour < 5)


def _fmt_money(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", " ")


def _month_short(value: date) -> str:
    return _format_rus_month(value)[:3]


LEAGUES: tuple[tuple[int, str, str | None, str], ...] = (
    (55, "Новичок", "Свой", "novice"),
    (75, "Свой", "Профи", "own"),
    (90, "Профи", "Ниндзя", "pro"),
    (101, "Ниндзя", None, "ninja"),
)


def _league_for(score: int) -> tuple[str, str | None, int | None, str]:
    for threshold, name, next_name, key in LEAGUES:
        if score < threshold:
            points = threshold - score if next_name else None
            return name, next_name, points, key
    return "Ниндзя", None, None, "ninja"


def _streak_state(spent: list[float], limits: list[float], count: int) -> tuple[int, int]:
    """Current streak and the best previous one. A zero-spend day is neutral."""
    finished: list[int] = []
    current = 0
    for i in range(count):
        day_spent = spent[i]
        if day_spent <= 0:
            continue
        if limits[i] > 0 and day_spent <= limits[i]:
            current += 1
        else:
            finished.append(current)
            current = 0
    return current, max(finished, default=0)


def _metric(
    metric_id: str,
    title: str,
    value: str,
    subtitle: str,
    bar: float = 0.0,
    frog: str | None = None,
) -> CardMetric:
    return CardMetric(
        id=metric_id,
        title=title,
        value=value,
        subtitle=subtitle,
        bar=max(0.0, min(1.0, bar)),
        frog=frog or metric_id,
    )


def compute_card_metrics(input: MonthlyCardInput) -> CardMetrics:
    """Pure metric layer for the 2×2 bento card."""
    days = list(input.daily_spent)
    total_days = max(1, (input.period_end - input.period_start).days + 1)
    base = float(input.daily_limit)
    limits = list(input.daily_limits or [])
    if len(limits) < len(days):
        limits.extend([base] * (len(days) - len(limits)))
    limits = limits[: len(days)]

    as_of = input.as_of
    if as_of is None:
        as_of = (
            input.period_end
            if not input.is_active
            else input.period_start + timedelta(days=max(len(days) - 1, 0))
        )
    today_index = None
    if input.is_active and days:
        idx = (as_of - input.period_start).days
        if 0 <= idx < len(days):
            today_index = idx
    completed_count = today_index if today_index is not None else len(days)
    completed_spent = days[:completed_count]
    completed_limits = limits[:completed_count]

    total_spent = float(input.total_spent or sum(days))
    active = bool(input.is_active)
    closed = not active and not input.upcoming

    current_limit = float(input.current_limit if input.current_limit is not None else base)
    if not active or base <= 0:
        current_limit = base
    limit_delta = (
        round(current_limit - base, 2)
        if active and base > 0 and input.current_limit is not None
        else None
    )

    tracked_days = [(s, lim) for s, lim in zip(completed_spent, completed_limits) if s > 0]
    green_days = [(s, lim) for s, lim in tracked_days if lim > 0 and s <= lim]
    green = len(green_days)
    tracked = len(tracked_days)
    green_pct = int(round(green / tracked * 100)) if tracked else 0

    overspend = sum(max(0.0, s - lim) for s, lim in tracked_days)
    sum_limits = sum(lim for _, lim in tracked_days)
    score = None
    if base > 0 and tracked >= 3 and sum_limits > 0:
        raw = 70 * (green / tracked) + 30 * max(0.0, 1 - overspend / sum_limits)
        score = int(round(max(0.0, min(100.0, raw))))
    league, next_league, points_to_next, league_key = (
        _league_for(score) if score is not None else (None, None, None, "")
    )

    streak, best_streak = _streak_state(completed_spent, completed_limits, completed_count)

    if active:
        elapsed = (as_of - input.period_start).days + 1
        passed_days = max(1, min(elapsed, total_days))
    else:
        passed_days = total_days
    avg_day = total_spent / passed_days if passed_days else 0.0
    forecast = avg_day * total_days
    tx_per_day = input.expenses_count / passed_days if passed_days else 0.0

    amounts = [float(e["amount"]) for e in input.expenses]
    median_check = statistics.median(amounts) if amounts else 0.0

    peak_scope = completed_count if completed_count else len(days)
    peak_idx = None
    if peak_scope:
        peak_idx = max(range(peak_scope), key=lambda i: days[i])
        if days[peak_idx] <= 0:
            peak_idx = None
    peak_callout = None
    if peak_idx is not None:
        peak_date = input.period_start + timedelta(days=peak_idx)
        peak_callout = f"{peak_date.day} {_month_short(peak_date)} · {_fmt_money(days[peak_idx])} ₽"

    top_expense: CardExpense | None = (
        max(input.expenses, key=lambda e: float(e["amount"])) if input.expenses else None
    )
    top_expense_amount = float(top_expense["amount"]) if top_expense else max(days, default=0.0)
    top_expense_category = (top_expense.get("category") if top_expense else None) or "Без категории"

    category_totals: dict[str, list[float]] = {}
    for expense in input.expenses:
        name = expense.get("category") or "Без категории"
        bucket = category_totals.setdefault(name, [0.0, 0.0])
        bucket[0] += float(expense["amount"])
        bucket[1] += 1
    top_category_name = None
    top_category_amount = 0.0
    top_category_count = 0
    if category_totals:
        top_category_name, (top_category_amount, top_category_count) = max(
            category_totals.items(),
            key=lambda item: (item[1][0], item[1][1], item[0]),
        )

    weekend_spent = sum(
        days[i]
        for i in range(completed_count)
        if (input.period_start + timedelta(days=i)).weekday() >= 5
    )
    completed_days = [input.period_start + timedelta(days=i) for i in range(completed_count)]
    has_weekday = any(day.weekday() < 5 for day in completed_days)
    has_weekend = any(day.weekday() >= 5 for day in completed_days)
    weekend_ok = has_weekday and has_weekend and total_spent > 0
    weekend_share = (weekend_spent / total_spent) if weekend_ok else 0.0
    weekend_pct = int(round(weekend_share * 100))

    night_amount = sum(float(e["amount"]) for e in input.expenses if _is_night_expense(e))
    latte_amount = sum(float(e["amount"]) for e in input.expenses if float(e["amount"]) <= 1000)

    top_n = 0
    top_share = 0.0
    if closed and tracked >= 7 and total_spent > 0:
        ordered = sorted(completed_spent, reverse=True)
        cumulative = 0.0
        for k in range(1, min(3, len(ordered)) + 1):
            cumulative += ordered[k - 1]
            share = cumulative / total_spent
            if share >= 0.45:
                top_n = k
                top_share = share
                break
    peak_days_ok = top_n > 0

    available_income = input.available_income
    if available_income is None:
        available_income = input.current_income
    budget_saved = round(available_income - total_spent, 2) if closed else None

    chart_limits = tuple(limits)

    def avg_card() -> CardMetric:
        return _metric(
            "avg_day",
            "СРЕДНИЙ ДЕНЬ",
            f"{_fmt_money(avg_day)} ₽",
            f"за {passed_days} {_plural_ru(passed_days, ('день', 'дня', 'дней'))}",
            bar=(avg_day / max(days, default=1)) if days else 0.0,
        )

    def top_expense_card() -> CardMetric:
        return _metric(
            "top_expense",
            "ДОРОГАЯ ПОКУПКА",
            f"{_fmt_money(top_expense_amount)} ₽",
            top_expense_category,
            bar=(top_expense_amount / total_spent) if total_spent > 0 else 0.0,
        )

    def top_category_card() -> CardMetric:
        if top_category_name is None:
            name = "Без категории"
            amount = total_spent
            pct = 100
        else:
            name = top_category_name
            amount = top_category_amount
            pct = int(round(amount / total_spent * 100)) if total_spent > 0 else 0
        return _metric(
            "top_category",
            "ТОП-КАТЕГОРИЯ",
            name,
            f"{_fmt_money(amount)} ₽ · {pct}%",
            bar=(amount / total_spent) if total_spent > 0 else 0.0,
        )

    def peak_days_card() -> CardMetric | None:
        if not peak_days_ok:
            return None
        share_pct = int(round(top_share * 100))
        verb = "сделал кассу" if top_n == 1 else "сделали кассу"
        return _metric(
            "peak_days",
            "ПИКОВЫЕ ДНИ",
            f"{share_pct}%",
            f"{top_n} {_plural_ru(top_n, ('день', 'дня', 'дней'))} {verb}",
            bar=top_share,
        )

    def habit_card(exclude_peak: bool = False) -> CardMetric | None:
        peak = None if exclude_peak else peak_days_card()
        weekend = (
            _metric(
                "weekend_tax",
                "НАЛОГ НА ВЫХОДНЫЕ",
                f"{weekend_pct}%",
                "трат ушло в выходные",
                bar=weekend_share,
            )
            if weekend_ok
            else None
        )
        night_share = (night_amount / total_spent) if total_spent > 0 else 0.0
        night = (
            _metric(
                "night_food",
                "НОЧНОЙ ДОЖОР",
                f"{_fmt_money(night_amount)} ₽",
                "после 21:00",
                bar=night_share,
            )
            if night_amount > 0
            else None
        )
        latte_share = (latte_amount / total_spent) if total_spent > 0 else 0.0
        latte = (
            _metric(
                "latte_effect",
                "ЭФФЕКТ ЛАТТЕ",
                f"{_fmt_money(latte_amount)} ₽",
                "чеки до 1 000 ₽",
                bar=latte_share,
            )
            if latte_amount > 0 and input.expenses_count >= 5
            else None
        )

        first: list[tuple[CardMetric, float]] = []
        if peak is not None:
            first.append((peak, top_share / 0.45))
        if weekend is not None:
            first.append((weekend, weekend_share / 0.40))
        second: list[tuple[CardMetric, float]] = []
        if night is not None:
            second.append((night, night_share / 0.15))
        if latte is not None:
            second.append((latte, latte_share / 0.15))

        best_first = max(first, key=lambda item: item[1]) if first else None
        if best_first is not None and best_first[1] >= 1.0:
            return best_first[0]
        best_second = max(second, key=lambda item: item[1]) if second else None
        if best_second is not None and best_second[1] >= 1.0:
            return best_second[0]
        return None

    if input.upcoming:
        wide = _metric(
            "upcoming",
            "ПЕРИОД ЕЩЁ НЕ НАЧАЛСЯ",
            f"с {input.period_start.day} {_format_rus_month(input.period_start)}",
            "здесь появится карта трат",
        )
        return CardMetrics(
            state="upcoming",
            cards=(),
            wide=wide,
            peak_callout=None,
            current_limit=current_limit,
            limit_delta=limit_delta,
            green=green,
            tracked=tracked,
            green_pct=green_pct,
            score=None,
            league=None,
            streak=0,
            best_streak=0,
            budget_saved=None,
            chart_limits=chart_limits,
            today_index=None,
        )

    if total_spent <= 0:
        quiet_id = "quiet_mode_closed" if closed else "quiet_mode"
        subtitle = (
            "за период — ни одной траты" if closed else "кошелёк отдыхает · начни с любой траты"
        )
        wide = _metric(
            quiet_id,
            "ТИШИНА" if closed else "РЕЖИМ ТИШИНЫ",
            "0 покупок",
            subtitle,
        )
        return CardMetrics(
            state="quiet",
            cards=(),
            wide=wide,
            peak_callout=None,
            current_limit=current_limit,
            limit_delta=limit_delta,
            green=green,
            tracked=tracked,
            green_pct=green_pct,
            score=None,
            league=None,
            streak=0,
            best_streak=0,
            budget_saved=budget_saved,
            chart_limits=chart_limits,
            today_index=today_index,
        )

    if base <= 0:
        slot1 = avg_card()
    elif active:
        if streak == 0:
            subtitle = "серия сброшена" if best_streak > 0 else "серия начнётся с траты"
            frog = "limit_streak_zero"
        elif best_streak == 0:
            subtitle = "первая серия периода"
            frog = "limit_streak_first"
        elif streak > best_streak:
            subtitle = "новая лучшая серия"
            frog = "limit_streak_record"
        elif streak == best_streak:
            subtitle = "повторяешь лучшую"
            frog = "limit_streak_repeat"
        else:
            subtitle = (
                f"до лучшей {best_streak - streak} "
                f"{_plural_ru(best_streak - streak, ('день', 'дня', 'дней'))}"
            )
            frog = "limit_streak_chasing"
        slot1 = _metric(
            "limit_streak",
            "СЕРИЯ",
            f"{streak} {_plural_ru(streak, ('день', 'дня', 'дней'))}",
            subtitle,
            bar=(streak / tracked) if tracked else 0.0,
            frog=frog,
        )
    else:
        winrate_frog = (
            "limit_winrate_clean"
            if green_pct >= 80
            else ("limit_winrate_rough" if green_pct < 50 else "limit_winrate")
        )
        slot1 = _metric(
            "limit_winrate",
            "ЗЕЛЁНЫЕ ДНИ",
            f"{green} из {tracked}",
            f"{green_pct}% в лимите",
            bar=(green / tracked) if tracked else 0.0,
            frog=winrate_frog,
        )

    peak_used = False
    if base <= 0:
        slot2 = peak_days_card() if closed else None
        if slot2 is None:
            slot2 = top_expense_card()
        else:
            peak_used = True
    elif score is not None:
        if next_league is not None and points_to_next is not None:
            subtitle = f"{league} · до {next_league} {points_to_next} б."
        else:
            subtitle = f"{league} · максимум"
        slot2 = _metric(
            "bro_score",
            "ФИН-СКОР",
            f"{score}/100",
            subtitle,
            bar=score / 100,
            frog=f"bro_score_{league_key}",
        )
    elif active:
        subtitle = "очень грубо · по 1 дню" if tracked == 1 else "к концу периода"
        slot2 = _metric(
            "forecast",
            "ПРОГНОЗ ЦИКЛА",
            f"{_fmt_money(forecast)} ₽",
            subtitle,
            bar=(forecast / (base * total_days)) if base > 0 else 0.0,
            frog="forecast_early" if tracked == 1 else "forecast",
        )
    else:
        slot2 = avg_card()

    used = {slot1.id, slot2.id}
    slot3 = habit_card(exclude_peak=peak_used)
    if slot3 is None or slot3.id in used:
        slot3 = top_category_card()

    tx_card = _metric(
        "tx_per_day",
        "ПОКУПОК В ДЕНЬ",
        f"{tx_per_day:.1f}".replace(".", ","),
        f"медиана чека {_fmt_money(median_check)} ₽",
        bar=min(1.0, tx_per_day / 5),
    )

    cards = (slot1, slot2, slot3, tx_card)
    return CardMetrics(
        state="active" if active else "closed",
        cards=cards,
        wide=None,
        peak_callout=peak_callout,
        current_limit=current_limit,
        limit_delta=limit_delta,
        green=green,
        tracked=tracked,
        green_pct=green_pct,
        score=score,
        league=league,
        streak=streak,
        best_streak=best_streak,
        budget_saved=budget_saved,
        chart_limits=chart_limits,
        today_index=today_index,
    )


def _input_to_json(input: MonthlyCardInput) -> str:
    return json.dumps(
        {
            "period_start": _date_str(input.period_start),
            "period_end": _date_str(input.period_end),
            "period_start_day": input.period_start_day,
            "daily_spent": [round(s, 2) for s in input.daily_spent],
            "daily_limit": round(input.daily_limit, 2),
            "daily_limits": [round(s, 2) for s in (input.daily_limits or [])],
            "total_spent": round(input.total_spent, 2),
            "expenses_count": input.expenses_count,
            "expenses": [
                {
                    "date": e["date"],
                    "amount": round(e["amount"], 2),
                    "category": e.get("category"),
                }
                for e in input.expenses
            ],
            "prev_expenses": [
                {
                    "date": e["date"],
                    "amount": round(e["amount"], 2),
                    "category": e.get("category"),
                }
                for e in (input.prev_expenses or [])
            ],
            "prev_period_start": (
                _date_str(input.prev_period_start) if input.prev_period_start else None
            ),
            "prev_period_end": (
                _date_str(input.prev_period_end) if input.prev_period_end else None
            ),
            "current_income": round(input.current_income, 2),
            "prev_income": round(input.prev_income, 2),
            "as_of": _date_str(input.as_of) if input.as_of else None,
            "is_active": input.is_active,
            "upcoming": input.upcoming,
            "current_limit": (
                round(input.current_limit, 2) if input.current_limit is not None else None
            ),
            "available_income": (
                round(input.available_income, 2) if input.available_income is not None else None
            ),
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _cached_render(input_json: str) -> bytes:
    input_data = json.loads(input_json)
    return _render_monthly_card_png_from_dict(input_data)


FROG_FALLBACKS = {
    "limit_streak_first": "limit_streak",
    "limit_streak_chasing": "limit_streak",
    "limit_streak_repeat": "limit_streak",
    "limit_streak_record": "limit_streak",
    "limit_streak_zero": "limit_streak",
    "limit_winrate_clean": "limit_winrate",
    "limit_winrate_rough": "limit_winrate",
    "bro_score_novice": "bro_score",
    "bro_score_own": "bro_score",
    "bro_score_pro": "bro_score",
    "bro_score_ninja": "bro_score",
    "forecast_early": "forecast",
    "quiet_mode_closed": "quiet_mode",
    "top_expense": "weekend_tax",
    "tx_per_day": "avg_day",
}


@functools.lru_cache(maxsize=64)
def _load_frog(frog_id: str):
    from pathlib import Path

    from PIL import Image

    candidates = [frog_id]
    fallback = FROG_FALLBACKS.get(frog_id)
    if fallback and fallback != frog_id:
        candidates.append(fallback)
    for name in candidates:
        path = Path(__file__).resolve().parents[1] / "assets" / "frogs" / f"{name}.png"
        if not path.exists():
            continue
        try:
            return Image.open(path).convert("RGBA")
        except Exception:
            logger.warning("Failed to load frog asset %s", path, exc_info=True)
    return None


def _paste_frog(img, frog_id: str, x: int, y: int, size: int = 48) -> None:
    from PIL import Image

    frog = _load_frog(frog_id)
    if frog is None:
        return
    frog = frog.resize((size, size), Image.LANCZOS)
    img.paste(frog, (int(x), int(y)), frog)


def _render_monthly_card_png_from_dict(data: dict) -> bytes:
    from PIL import Image, ImageDraw

    bg = "#0B0F14"
    card_bg = "#111822"
    border = "#1E293B"
    text_primary = "#F5F7FA"
    text_secondary = "#8A99A8"
    accent_blue = "#1C6CFF"
    accent_fill = (28, 108, 255, 56)
    limit_yellow = "#FACC15"
    accent_red = "#FF4433"
    accent_green = "#4CC38A"
    accent_purple = "#A78BFA"
    accent_pink = "#F472B6"

    w, h = 900, 840
    margin = 32
    img = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(img)

    input_data = MonthlyCardInput(
        period_start=date.fromisoformat(data["period_start"]),
        period_end=date.fromisoformat(data["period_end"]),
        period_start_day=int(data["period_start_day"]),
        daily_spent=list(data["daily_spent"]),
        daily_limit=float(data["daily_limit"]),
        total_spent=float(data["total_spent"]),
        expenses=list(data.get("expenses") or []),
        expenses_count=int(data.get("expenses_count") or 0),
        as_of=date.fromisoformat(data["as_of"]) if data.get("as_of") else None,
        is_active=bool(data.get("is_active")),
        upcoming=bool(data.get("upcoming")),
        daily_limits=data.get("daily_limits") or None,
        current_limit=(
            float(data["current_limit"]) if data.get("current_limit") is not None else None
        ),
        available_income=(
            float(data["available_income"]) if data.get("available_income") is not None else None
        ),
    )
    metrics = compute_card_metrics(input_data)

    font_title = _load_font("bold", 27)
    font_sub = _load_font("regular", 15)
    font_pill = _load_font("semibold", 13)
    font_axis = _load_font("regular", 12)
    font_callout = _load_font("semibold", 13)
    font_card_title = _load_font("semibold", 12)
    font_card_sub = _load_font("regular", 14)

    def rounded(xy, radius, fill, outline=None, width=1):
        draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)

    def text_width(text, font):
        return draw.textlength(text, font=font)

    def fit_font(text, weight, sizes, max_width):
        for size in sizes:
            font = _load_font(weight, size)
            if text_width(text, font) <= max_width:
                return font
        return _load_font(weight, sizes[-1])

    def truncate(text, font, max_width):
        if text_width(text, font) <= max_width:
            return text
        tail = "…"
        while text and text_width(text + tail, font) > max_width:
            text = text[:-1]
        return text.rstrip() + tail

    def axis_label(value):
        if value >= 1_000_000:
            return f"{value / 1_000_000:.1f}M".replace(".", ",")
        if value >= 100_000:
            return f"{value / 1000:.0f}k"
        return _fmt_money(value)

    def nice_step(value):
        if value <= 0:
            return 1.0
        magnitude = 1.0
        while magnitude * 10 <= value:
            magnitude *= 10
        for multiplier in (1, 2, 5, 10):
            step = multiplier * magnitude
            if step >= value:
                return step
        return 10 * magnitude

    def dashed_horizontal(x0, x1, y, color, dash=6, gap=5, width=1):
        x = x0
        while x < x1:
            draw.line([(x, y), (min(x + dash, x1), y)], fill=color, width=width)
            x += dash + gap

    def dashed_vertical(x, y0, y1, color, dash=6, gap=5, width=1):
        y = min(y0, y1)
        end = max(y0, y1)
        while y < end:
            draw.line([(x, y), (x, min(y + dash, end))], fill=color, width=width)
            y += dash + gap

    # ─── Header ───
    header_y = 26
    period_text = _format_rus_period(
        input_data.period_start,
        input_data.period_end,
        input_data.period_start_day,
    )
    draw.text((margin, header_y), f"Траты · {period_text}", font=font_title, fill=text_primary)
    purchases = _plural_ru(input_data.expenses_count, ("покупка", "покупки", "покупок"))
    draw.text(
        (margin, header_y + 39),
        f"Всего {_fmt_money(input_data.total_spent)} ₽ · {input_data.expenses_count} {purchases}",
        font=font_sub,
        fill=text_secondary,
    )

    if input_data.daily_limit > 0 and not input_data.upcoming:
        limit_segments = [
            ("Лимит: ", text_primary),
            (f"{_fmt_money(metrics.current_limit)} ₽/д", limit_yellow),
        ]
        if metrics.limit_delta is not None:
            delta = metrics.limit_delta
            if delta > 0:
                delta_color = accent_green
                sign = "+"
            elif delta < 0:
                delta_color = accent_red
                sign = "-"
            else:
                delta_color = text_secondary
                sign = ""
            limit_segments.append((f" ({sign}{_fmt_money(abs(delta))} ₽)", delta_color))

        if input_data.is_active:
            if metrics.green_pct >= 70:
                discipline_color = accent_green
            elif metrics.green_pct >= 50:
                discipline_color = limit_yellow
            else:
                discipline_color = accent_red
            discipline = f"{metrics.green_pct}% в лимите ({metrics.green}/{metrics.tracked} дн.)"
        else:
            saved = metrics.budget_saved or 0.0
            if saved >= 0:
                discipline_color = accent_green
                discipline = "в бюджете"
            else:
                discipline_color = accent_red
                discipline = f"перерасход: {_fmt_money(abs(saved))} ₽"
        discipline_segments = [(discipline, discipline_color)]

        def pill_width(segments):
            return sum(text_width(text, font_pill) for text, _ in segments) + 28

        first_w = pill_width(limit_segments)
        second_w = pill_width(discipline_segments)
        right = w - margin
        for segments, width, y in (
            (limit_segments, first_w, header_y - 2),
            (discipline_segments, second_w, header_y + 38),
        ):
            x = right - width
            rounded((x, y, x + width, y + 32), 16, card_bg, border, 1)
            cursor = x + 14
            for text, color in segments:
                draw.text((cursor, y + 8), text, font=font_pill, fill=color)
                cursor += text_width(text, font_pill)

    def draw_wide_card(card) -> None:
        x, y, cw, ch = margin, 150, w - margin * 2, 630
        rounded((x, y, x + cw, y + ch), 16, card_bg, border, 1)
        accent = text_secondary
        content_y = y + ch // 2 - 90
        draw.ellipse([x + 24, content_y + 6, x + 32, content_y + 14], fill=accent)
        draw.text((x + 42, content_y), card.title, font=font_card_title, fill=accent)
        value_font = fit_font(card.value, "bold", [42, 36, 30], cw - 160)
        draw.text(
            (x + 24, content_y + 54),
            truncate(card.value, value_font, cw - 160),
            font=value_font,
            fill=text_primary,
        )
        draw.text(
            (x + 24, content_y + 124),
            truncate(card.subtitle, font_card_sub, cw - 160),
            font=font_card_sub,
            fill=text_secondary,
        )
        _paste_frog(
            img,
            card.frog,
            x + cw - 24 - 96,
            y + (ch - 96) // 2,
            96,
        )

    if metrics.wide is not None:
        draw_wide_card(metrics.wide)
    else:
        days = list(input_data.daily_spent)
        limits = list(metrics.chart_limits)
        n = len(days)

        chart_x, chart_y, chart_w, chart_h = margin, 116, w - margin * 2, 316
        rounded((chart_x, chart_y, chart_x + chart_w, chart_y + chart_h), 16, card_bg, border, 1)
        pad_left, pad_right, pad_top, pad_bottom = 62, 24, 34, 38
        inner_x = chart_x + pad_left
        inner_y = chart_y + pad_top
        inner_w = chart_w - pad_left - pad_right
        inner_h = chart_h - pad_top - pad_bottom

        max_raw = max([*days, *limits, 1.0])
        step = nice_step(max_raw / 5)
        max_y = step * 5

        def y_of(value):
            return inner_y + inner_h * (1 - value / max_y)

        for i in range(6):
            value = step * i
            y = y_of(value)
            draw.line([(inner_x, y), (inner_x + inner_w, y)], fill=border, width=1)
            draw.text(
                (inner_x - 10, y - 5),
                axis_label(value),
                font=font_axis,
                fill=text_secondary,
                anchor="ra",
            )

        if n > 0:
            if n == 1:
                points = [(inner_x + inner_w / 2, y_of(days[0]))]
            else:
                points = [(inner_x + i * inner_w / (n - 1), y_of(days[i])) for i in range(n)]

            for i in range(n):
                if n > 1:
                    x0 = inner_x + i * inner_w / (n - 1)
                    x1 = inner_x + (i + 1) * inner_w / (n - 1) if i < n - 1 else x0
                else:
                    x0, x1 = inner_x, inner_x + inner_w
                dashed_horizontal(x0, x1, y_of(limits[i]), limit_yellow)
                if i < n - 1 and limits[i] != limits[i + 1]:
                    dashed_vertical(
                        x1,
                        y_of(limits[i]),
                        y_of(limits[i + 1]),
                        limit_yellow,
                    )

            if n > 1:
                fill_points = points + [
                    (inner_x + inner_w, inner_y + inner_h),
                    (inner_x, inner_y + inner_h),
                ]
                fill_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                ImageDraw.Draw(fill_layer).polygon(fill_points, fill=accent_fill)
                img.paste(Image.alpha_composite(img.convert("RGBA"), fill_layer).convert("RGB"))
                draw = ImageDraw.Draw(img)
                for i in range(n - 1):
                    draw.line([points[i], points[i + 1]], fill=accent_blue, width=3, joint="curve")

            for i in range(n):
                if i == metrics.today_index:
                    continue
                point_x, point_y = points[i]
                if days[i] > 0 and limits[i] > 0 and days[i] <= limits[i]:
                    draw.ellipse(
                        [point_x - 2.5, point_y - 2.5, point_x + 2.5, point_y + 2.5],
                        fill=accent_green,
                    )
                if limits[i] > 0 and days[i] > limits[i]:
                    draw.ellipse(
                        [point_x - 4.5, point_y - 4.5, point_x + 4.5, point_y + 4.5],
                        fill=accent_red,
                    )

            completed = metrics.today_index if metrics.today_index is not None else n
            peak_scope = completed if completed else n
            peak_idx = max(range(peak_scope), key=lambda i: days[i]) if peak_scope else None
            if peak_idx is not None and days[peak_idx] > 0:
                peak_x, peak_y = points[peak_idx]
                if peak_idx != metrics.today_index:
                    draw.ellipse(
                        [peak_x - 7, peak_y - 7, peak_x + 7, peak_y + 7],
                        outline=accent_red,
                        width=2,
                    )
                if metrics.peak_callout:
                    callout = metrics.peak_callout
                    callout_w = text_width(callout, font_callout) + 20
                    callout_h = 26
                    tx = peak_x - callout_w / 2
                    tx = max(chart_x + 12, min(tx, chart_x + chart_w - callout_w - 12))
                    ty = max(chart_y + 56, peak_y - callout_h - 10)
                    rounded((tx, ty, tx + callout_w, ty + callout_h), 6, card_bg, accent_red, 1)
                    draw.text((tx + 10, ty + 5), callout, font=font_callout, fill=text_primary)

            if metrics.today_index is not None and 0 <= metrics.today_index < n:
                today_x, today_y = points[metrics.today_index]
                draw.ellipse(
                    [today_x - 6, today_y - 6, today_x + 6, today_y + 6],
                    fill=card_bg,
                    outline=text_primary,
                    width=2,
                )

            label_step = max(1, (n - 1) // 5) if n > 1 else 1
            label_indices = list(range(0, n, label_step))
            if label_indices and label_indices[-1] != n - 1:
                label_indices.append(n - 1)
            for i in label_indices:
                label_date = input_data.period_start + timedelta(days=i)
                draw.text(
                    (points[i][0], inner_y + inner_h + 10),
                    f"{label_date.day} {_month_short(label_date)}",
                    font=font_axis,
                    fill=text_secondary,
                    anchor="ma",
                )

        card_w = (w - margin * 2 - 16) // 2
        card_h = 170
        first_row_y = 448
        second_row_y = first_row_y + card_h + 16

        accents = {
            "limit_streak": limit_yellow,
            "limit_winrate": accent_green,
            "avg_day": text_secondary,
            "bro_score": (
                accent_green
                if (metrics.score or 0) >= 90
                else limit_yellow
                if (metrics.score or 0) >= 55
                else text_secondary
            ),
            "forecast": accent_purple,
            "top_category": limit_yellow,
            "top_expense": accent_red,
            "peak_days": accent_red,
            "weekend_tax": accent_purple,
            "night_food": accent_pink,
            "latte_effect": accent_pink,
            "tx_per_day": text_secondary,
        }

        for index, card in enumerate(metrics.cards[:4]):
            x = margin + (index % 2) * (card_w + 16)
            y = first_row_y if index < 2 else second_row_y
            accent = accents.get(card.id, text_secondary)
            rounded((x, y, x + card_w, y + card_h), 16, card_bg, border, 1)
            draw.ellipse([x + 20, y + 20, x + 28, y + 28], fill=accent)
            draw.text((x + 36, y + 14), card.title, font=font_card_title, fill=accent)
            value_w = card_w - 40 - 68
            value_font = fit_font(card.value, "bold", [32, 28, 24, 20], value_w)
            draw.text(
                (x + 20, y + 50),
                truncate(card.value, value_font, value_w),
                font=value_font,
                fill=text_primary,
            )
            draw.text(
                (x + 20, y + 102),
                truncate(card.subtitle, font_card_sub, value_w),
                font=font_card_sub,
                fill=text_secondary,
            )
            bar_y = y + 144
            bar_x0 = x + 20
            bar_x1 = x + card_w - 84
            rounded((bar_x0, bar_y, bar_x1, bar_y + 6), 3, border)
            if card.bar > 0:
                rounded(
                    (bar_x0, bar_y, bar_x0 + (bar_x1 - bar_x0) * card.bar, bar_y + 6),
                    3,
                    accent,
                )
            _paste_frog(img, card.frog, x + card_w - 68, y + (card_h - 48) // 2, 48)

    from io import BytesIO

    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True, compress_level=6)
    return buf.getvalue()


def render_monthly_card_png(input: MonthlyCardInput) -> bytes:
    input_json = _input_to_json(input)
    return _cached_render(input_json)


# ──────────────────────────────────────────────────────────────────────
# Widget HTML (kept for fallback)
# ──────────────────────────────────────────────────────────────────────

# ruff: noqa: E501
CHART_WIDGET_HTML = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font: 11px/1.3 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: var(--tg-theme-bg-color, #ffffff); color: var(--tg-theme-text-color, #000000); min-height: 230px; position: relative; }
#chart { display: block; width: 100%; height: 190px; }
.caption { text-align: center; font-size: 11px; color: var(--tg-theme-hint-color, #999999); margin: 4px 0 0; }
.tooltip { position: absolute; pointer-events: none; background: var(--tg-theme-secondary-bg-color, #f0f0f0); color: var(--tg-theme-text-color, #000000); padding: 4px 8px; border-radius: 4px; font-size: 10px; white-space: nowrap; transform: translate(-50%, -100%); margin-bottom: 4px; display: none; z-index: 10; }
.tooltip.visible { display: block; }
.bar { cursor: pointer; transition: opacity 0.1s; }
.bar:hover { opacity: 0.7; }
.bar.selected { opacity: 1; }
.bar-over { fill: var(--tg-theme-destructive-text-color, #ff3b30); }
.bar-ok { fill: var(--tg-theme-button-color, #2481cc); }
.limit-line { stroke: var(--tg-theme-hint-color, #999999); stroke-width: 1; stroke-dasharray: 4 3; }
.axis { stroke: var(--tg-theme-hint-color, #999999); stroke-width: 0.5; }
.tick text { fill: var(--tg-theme-hint-color, #999999); font-size: 8px; }
.selected-tick text { fill: var(--tg-theme-button-color, #2481cc); font-weight: 600; }
.hint-text { text-align: center; font-size: 10px; color: var(--tg-theme-hint-color, #999999); margin-top: 2px; }
</style>
</head>
<body>
<svg id="chart"></svg>
<div class="caption" id="caption"></div>
<div class="tooltip" id="tooltip"></div>
<div class="hint-text" id="hint">Нажми на день, чтобы увидеть детали</div>
<script>
// Telegram Widget API
const widget = window.TelegramWidget;
if (!widget) { document.body.innerHTML = '<p style="padding:20px;text-align:center;color:var(--tg-theme-hint-color, #999999)">Виджет недоступен</p>'; throw 0; }

let state = {m: "", s: "", d: [], lim: 0, a: false};
let selectedIndex = -1;
const svg = document.getElementById('chart');
const tooltip = document.getElementById('tooltip');
const caption = document.getElementById('caption');
const hint = document.getElementById('hint');

// Initial render from chatData (no flash)
if (widget.chatData?.d) {
    state = widget.chatData;
    render();
}

// Request initial data (for first load)
widget.requestData?.();

function render() {
  if (!state.d || !state.d.length) return;
  const days = state.d;
  const baseLimit = state.lim || 0;
  const n = days.length;
  const padding = { top: 10, right: 10, bottom: 20, left: 30 };
  const w = svg.clientWidth || 300;
  const h = 190;
  const innerW = w - padding.left - padding.right;
  const innerH = h - padding.top - padding.bottom;
  const barW = Math.max(3, innerW / n - 1);

  let maxVal = baseLimit;
  for (const v of days) { if (v > maxVal) maxVal = v; }
  maxVal = Math.max(maxVal, 1) * 1.15;

  const yScale = v => padding.top + innerH * (1 - v / maxVal);
  const xScale = i => padding.left + i * (innerW / n) + (innerW / n - barW) / 2;

  let svgHTML = '';
  svgHTML += `<line class="axis" x1="${padding.left}" y1="${padding.top}" x2="${padding.left}" y2="${padding.top + innerH}"/>`;
  svgHTML += `<line class="axis" x1="${padding.left}" y1="${padding.top + innerH}" x2="${w - padding.right}" y2="${padding.top + innerH}"/>`;
  if (baseLimit > 0) {
    const ly = yScale(baseLimit);
    svgHTML += `<line class="limit-line" x1="${padding.left}" y1="${ly}" x2="${w - padding.right}" y2="${ly}"/>`;
    svgHTML += `<text x="${padding.left - 4}" y="${ly - 2}" text-anchor="end" font-size="8" fill="var(--tg-theme-hint-color, #999999)">${fmt(baseLimit)}</text>`;
  }
  for (let i = 0; i < n; i++) {
    const spent = days[i];
    const x = xScale(i);
    const barH = innerH * (spent / maxVal);
    const y = yScale(spent);
    const cls = spent > baseLimit && baseLimit > 0 ? 'bar bar-over' : 'bar bar-ok';
    const sel = i === selectedIndex ? ' selected' : '';
    svgHTML += `<rect class="${cls}${sel}" x="${x}" y="${y}" width="${barW}" height="${barH}" data-index="${i}" rx="1"/>`;
    svgHTML += `<rect class="bar" fill="transparent" x="${x}" y="${padding.top}" width="${barW}" height="${innerH}" data-index="${i}"/>`;
  }
  const step = Math.max(1, Math.ceil(n / 6));
  for (let i = 0; i < n; i += step) {
    const x = padding.left + (i + 0.5) * (innerW / n);
    const cls = i === selectedIndex ? 'tick selected-tick' : 'tick';
    svgHTML += `<g class="${cls}"><line x1="${x}" y1="${padding.top + innerH}" x2="${x}" y2="${padding.top + innerH + 4}"/><text x="${x}" y="${padding.top + innerH + 14}" text-anchor="middle">${formatDate(i)}</text></g>`;
  }
  if (n - 1 > 0 && (n - 1) % step !== 0) {
    const x = padding.left + (n - 0.5) * (innerW / n);
    svgHTML += `<g class="tick"><line x1="${x}" y1="${padding.top + innerH}" x2="${x}" y2="${padding.top + innerH + 4}"/><text x="${x}" y="${padding.top + innerH + 14}" text-anchor="middle">${formatDate(n - 1)}</text></g>`;
  }

  svg.innerHTML = svgHTML;
  caption.textContent = `📊 Траты по дням · ${state.m} (${n} дн.)`;

  svg.querySelectorAll('[data-index]').forEach(el => {
    el.addEventListener('click', e => {
      const idx = parseInt(e.currentTarget.dataset.index, 10);
      if (idx === selectedIndex) {
        selectedIndex = -1;
        tooltip.classList.remove('visible');
        hint.textContent = 'Нажми на день, чтобы увидеть детали';
      } else {
        selectedIndex = idx;
        showTooltip(idx);
        widget.hapticFeedback?.('selectionChanged');
      }
      render();
    });
  });
}

function formatDate(idx) {
  const start = new Date(state.s + 'T00:00:00');
  const d = new Date(start);
  d.setDate(start.getDate() + idx);
  return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' });
}

function showTooltip(idx) {
  const spent = state.d[idx];
  const diff = spent - state.lim;
  const dateStr = formatDate(idx);
  const spentStr = fmt(spent);
  const limitStr = fmt(state.lim);
  const diffStr = diff >= 0 ? '+' + fmt(diff) : fmt(diff);
  const diffColor = diff > 0 ? 'var(--tg-theme-destructive-text-color, #ff3b30)' : 'var(--tg-theme-text-color, #000000)';
  tooltip.innerHTML = `<b>${dateStr}</b><br>Потрачено: ${spentStr} ₽<br>Лимит: ${limitStr} ₽<br><span style="color:${diffColor}">Разница: ${diffStr} ₽</span>`;
  const rect = svg.querySelector(`[data-index="${idx}"].bar-over, [data-index="${idx}"].bar-ok`);
  if (rect) {
    const svgRect = svg.getBoundingClientRect();
    const barRect = rect.getBoundingClientRect();
    const svgW = svg.clientWidth || 300;
    let left = barRect.left - svgRect.left + rect.width.baseVal.value / 2;
    let top = barRect.top - svgRect.top - 4;
    left = Math.max(55, Math.min(svgW - 55, left));
    if (top < 42) {
      top = barRect.top - svgRect.top + barRect.height + 8;
    }
    tooltip.style.left = left + 'px';
    tooltip.style.top = top + 'px';
    tooltip.classList.add('visible');
  }
  hint.textContent = 'Нажми ещё раз, чтобы скрыть';
}

function fmt(n) {
  return Math.round(n).toLocaleString('ru-RU');
}

widget.on('chatDataChanged', data => {
  if (data && data.d) {
    state = data;
    selectedIndex = -1;
    tooltip.classList.remove('visible');
    hint.textContent = 'Нажми на день, чтобы увидеть детали';
    render();
  }
});

widget.requestData?.();

</script>
</body>
</html>
"""


def validate_widget_html() -> bool:
    compressed = zlib.compress(CHART_WIDGET_HTML.encode("utf-8"))
    return len(compressed) <= 4096


if not validate_widget_html():
    logger.warning("Widget HTML exceeds 4096 bytes after zlib compression")
