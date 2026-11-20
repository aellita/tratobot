"""Monthly chart: PNG card rendering (Financial Bro style) + Widget state/HTML."""

import functools
import json
import logging
import zlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TypedDict

from sqlalchemy import func, select

from ..db.database import async_session_maker
from ..db.models.models import Budget, Expense
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


async def _fetch_card_expenses(
    telegram_id: int,
    start: datetime,
    end: datetime,
) -> list[CardExpense]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Expense.date, Expense.amount)
            .where(Expense.telegram_id == telegram_id)
            .where(Expense.date >= start)
            .where(Expense.date < end)
            .where(Expense.is_deleted == False)
        )
        return [
            CardExpense(date=expense_date.isoformat(), amount=float(amount))
            for expense_date, amount in result.all()
        ]


async def build_monthly_card_input(
    telegram_id: int,
    budget: Budget,
    prev_budget: Budget | None = None,
    daily_limit: float | None = None,
) -> MonthlyCardInput:
    period_start, period_end = period_dates(budget.month, budget.period_start_day or 1)
    _, end_date, _ = _chart_window(budget)
    chart_data = await build_chart_data(telegram_id, budget)
    daily_spent = [round(day["spent"], 2) for day in chart_data]

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

    return MonthlyCardInput(
        period_start=period_start.date(),
        period_end=period_end.date(),
        period_start_day=budget.period_start_day or 1,
        daily_spent=daily_spent,
        daily_limit=float(
            daily_limit if daily_limit is not None else _compute_base_daily_limit(budget)
        ),
        total_spent=round(sum(daily_spent), 2),
        expenses=expenses,
        expenses_count=len(expenses),
        prev_expenses=prev_expenses,
        prev_period_start=prev_period_start,
        prev_period_end=prev_period_end,
        current_income=float((budget.total_income or 0) + (budget.added_income or 0)),
        prev_income=prev_income,
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


def _wrap_text(draw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines = []
    current = []
    for word in words:
        if not current and draw.textlength(word, font=font) > max_width:
            lines.append(word)
            continue
        test = " ".join(current + [word])
        if draw.textlength(test, font=font) <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return [line for line in lines if line]


def _date_str(value: date | datetime) -> str:
    return value.strftime("%Y-%m-%d")


def _parse_date(value: str) -> date:
    """Parse both ``YYYY-MM-DD`` and full ISO datetime strings."""
    return datetime.fromisoformat(value).date()


def _expense_hour(expense: CardExpense) -> int:
    try:
        return datetime.fromisoformat(expense["date"]).hour
    except (TypeError, ValueError):
        return 0


def _input_to_json(input: MonthlyCardInput) -> str:
    return json.dumps(
        {
            "period_start": _date_str(input.period_start),
            "period_end": _date_str(input.period_end),
            "period_start_day": input.period_start_day,
            "daily_spent": [round(s, 2) for s in input.daily_spent],
            "daily_limit": round(input.daily_limit, 2),
            "total_spent": round(input.total_spent, 2),
            "expenses_count": input.expenses_count,
            "expenses": [
                {"date": e["date"], "amount": round(e["amount"], 2)} for e in input.expenses
            ],
            "prev_expenses": [
                {"date": e["date"], "amount": round(e["amount"], 2)}
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
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _cached_render(input_json: str) -> bytes:
    input_data = json.loads(input_json)
    return _render_monthly_card_png_from_dict(input_data)


def _render_monthly_card_png_from_dict(data: dict) -> bytes:
    from PIL import Image, ImageDraw

    # ─── Palette (Financial Bro Dark) ───
    # ruff: noqa: N806
    bg_canvas = "#17212B"
    text_secondary = "#8A99A8"
    accent_blue = "#3390EC"
    accent_coral = "#E56B6F"
    accent_green = "#4CC38A"
    accent_amber = "#EAB308"
    accent_purple = "#A78BFA"
    accent_pink = "#F472B6"
    limit_amber = "#FBBF24"
    text_primary = "#F5F5F5"

    # ─── Canvas ───
    w, h = 900, 620
    img = Image.new("RGB", (w, h), bg_canvas)
    draw = ImageDraw.Draw(img)

    # ─── Fonts ───
    font_title = _load_font("bold", 26)
    font_sub = _load_font("regular", 16)
    font_metric = _load_font("bold", 26)
    font_chip = _load_font("semibold", 15)
    font_axis = _load_font("regular", 11)
    font_tooltip = _load_font("semibold", 13)

    # ─── Unpack data ───
    daily_spent = data["daily_spent"]
    total_spent = data["total_spent"]
    expenses_count = data["expenses_count"]
    expenses = data.get("expenses", [])
    prev_expenses = data.get("prev_expenses", [])
    current_income = data["current_income"]
    prev_income = data["prev_income"]

    passed_days = len(daily_spent)

    # ─── Helpers ───
    def fmt_money(v: float) -> str:
        return f"{int(round(v)):,}".replace(",", " ")

    def fmt_pct(v: float) -> str:
        return f"{int(round(v))}%"

    # ─── Card drawing helpers ───
    def draw_rounded_rect(xy, radius, fill, outline=None, width=1):
        x1, y1, x2, y2 = xy
        draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)

    # ════════════════════════════════════════════════════════════════════
    # 1. HEADER (y: 32..96)
    # ════════════════════════════════════════════════════════════════════
    header_y = 32
    period_text = _format_rus_period(
        date.fromisoformat(data["period_start"]),
        date.fromisoformat(data["period_end"]),
        data["period_start_day"],
    )

    # Period title
    draw.text((36, header_y), f"Траты · {period_text}", font=font_title, fill=text_primary)

    # Subtitle
    draw.text(
        (36, header_y + 34),
        f"Всего потрачено: {fmt_money(total_spent)} ₽ · {expenses_count} покупок",
        font=font_sub,
        fill=text_secondary,
    )

    # Limit badge (right side)
    if data["daily_limit"] > 0:
        badge_text = f"Лимит: {fmt_money(data['daily_limit'])} ₽/день"
        badge_w = draw.textlength(badge_text, font=font_chip) + 24
        badge_x = w - 36 - badge_w
        badge_y = header_y - 2
        draw_rounded_rect(
            (badge_x, badge_y, badge_x + badge_w, badge_y + 38), 19, "#1E222D", "#323746", 1
        )
        draw.text((badge_x + 12, badge_y + 8), badge_text, font=font_chip, fill=limit_amber)

    # ════════════════════════════════════════════════════════════════════
    # 2. CHART AREA (y: 112..416)
    # ═══════════════════════════════════════════════════════════════════
    chart_x = 36
    chart_y = 112
    chart_w = 828
    chart_h = 304
    padding_chart = {"left": 68, "right": 28, "top": 36, "bottom": 42}

    inner_x = chart_x + padding_chart["left"]
    inner_y = chart_y + padding_chart["top"]
    inner_w = chart_w - padding_chart["left"] - padding_chart["right"]
    inner_h = chart_h - padding_chart["top"] - padding_chart["bottom"]

    # Chart card background
    draw_rounded_rect(
        (chart_x, chart_y, chart_x + chart_w, chart_y + chart_h), 24, "#171920", "#262934", 1
    )

    # Grid lines
    max_spent = max(daily_spent) if daily_spent else 1
    max_y = max(max_spent, data["daily_limit"]) if data["daily_limit"] > 0 else max_spent
    max_y = max(max_y, 1) * 1.15

    # Horizontal grid lines (3 lines)
    for i in range(4):
        gy = inner_y + inner_h * i / 3
        draw.line([(inner_x, gy), (inner_x + inner_w, gy)], fill="#222530", width=1)

    # Y-axis labels
    for i in range(4):
        val = max_y * (3 - i) / 3
        label = fmt_money(val) if val >= 1000 else f"{int(val):,}"
        draw.text(
            (inner_x - 60, inner_y + inner_h * i / 3 - 7),
            label,
            font=font_axis,
            fill=text_secondary,
            anchor="ra",
        )

    # Limit line
    if data["daily_limit"] > 0 and data["daily_limit"] <= max_y * 1.3:
        lim_y = inner_y + inner_h * (1 - data["daily_limit"] / max_y)
        # Dashed line
        dash_len = 8
        gap_len = 6
        x = inner_x
        while x < inner_x + inner_w:
            end_x = min(x + dash_len, inner_x + inner_w)
            draw.line([(x, lim_y), (end_x, lim_y)], fill=limit_amber + "A0", width=1)
            x += dash_len + gap_len
        # "лимит" label
        draw.text(
            (inner_x + inner_w + 8, lim_y - 7),
            "лимит",
            font=font_axis,
            fill=limit_amber + "A0",
            anchor="la",
        )

    # Data line (polyline)
    n = len(daily_spent)
    if n > 1:
        step_x = inner_w / (n - 1)
        points = []
        for i, spent in enumerate(daily_spent):
            x = inner_x + i * step_x
            y = inner_y + inner_h * (1 - spent / max_y)
            points.append((x, y))

        # Fill area under line (polygon)
        fill_points = points + [
            (inner_x + inner_w, inner_y + inner_h),
            (inner_x, inner_y + inner_h),
        ]
        fill_img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        fill_draw = ImageDraw.Draw(fill_img)
        fill_draw.polygon(fill_points, fill=(51, 144, 236, 90))
        img = Image.alpha_composite(img.convert("RGBA"), fill_img).convert("RGB")
        draw = ImageDraw.Draw(img)

        # Line
        for i in range(len(points) - 1):
            draw.line([points[i], points[i + 1]], fill=accent_blue, width=3, joint="curve")

        # Peak dots (over limit)
        if data["daily_limit"] > 0:
            for i, spent in enumerate(daily_spent):
                if spent > data["daily_limit"]:
                    x, y = points[i]
                    draw.ellipse(
                        [x - 6, y - 6, x + 6, y + 6], fill=accent_coral, outline=bg_canvas, width=2
                    )

        # Tooltip for max peak
        if daily_spent:
            max_idx = max(range(len(daily_spent)), key=lambda i: daily_spent[i])
            max_spent = daily_spent[max_idx]
            mx, my = points[max_idx]
            peak_date = date.fromisoformat(data["period_start"]) + timedelta(days=max_idx)
            date_str = f"{peak_date.day} {_format_rus_month(peak_date)[:3]}"
            tooltip_text = f"{date_str} · {fmt_money(max_spent)} ₽"
            tw = draw.textlength(tooltip_text, font=font_tooltip)
            pad_x, pad_y = 10, 6
            tx = mx - tw / 2 - pad_x
            ty = my - 40 - pad_y * 2
            # Clamp
            tx = max(chart_x + 10, min(tx, chart_x + chart_w - tw - 2 * pad_x - 10))
            ty = max(chart_y + 10, ty)
            # Tooltip background
            draw_rounded_rect(
                (tx - pad_x, ty - pad_y, tx + tw + 2 * pad_x, ty + 2 * pad_y + font_tooltip.size),
                6,
                "#131C26",
                accent_coral,
                1,
            )
            draw.text((tx, ty + pad_y), tooltip_text, font=font_tooltip, fill=text_primary)

    # X-axis labels (5-6 labels)
    if n > 1:
        step = max(1, (n - 1) // 5)
        for i in range(0, n, step):
            x = inner_x + i * step_x
            d = date.fromisoformat(data["period_start"]) + timedelta(days=i)
            label = f"{d.day} {_format_rus_month(d)[:3]}"
            draw.text(
                (x, inner_y + inner_h + 8), label, font=font_axis, fill=text_secondary, anchor="ma"
            )
        # Last day
        if (n - 1) % step != 0:
            x = inner_x + (n - 1) * step_x
            d = date.fromisoformat(data["period_start"]) + timedelta(days=n - 1)
            label = f"{d.day} {_format_rus_month(d)[:3]}"
            draw.text(
                (x, inner_y + inner_h + 8), label, font=font_axis, fill=text_secondary, anchor="ma"
            )

    # Empty state
    if not daily_spent or max(daily_spent) == 0:
        draw.text(
            (w / 2, chart_y + chart_h / 2),
            "За этот период трат пока нет",
            font=font_sub,
            fill=text_secondary,
            anchor="mm",
        )

    # ════════════════════════════════════════════════════════════════════
    # 3. INSIGHTS ROW (y: 436..584)
    # ═══════════════════════════════════════════════════════════════════
    insight_y = 436
    insight_h = 148
    gap = 18
    card_w = (w - 36 * 2 - gap * 2) // 3

    # ─── Compute insights ───
    passed_days = len(daily_spent)

    # Slot 1: peak_day
    peak_idx = max(range(len(daily_spent)), key=lambda i: daily_spent[i]) if daily_spent else 0
    peak_day = daily_spent[peak_idx] if daily_spent else 0.0
    period_start_date = date.fromisoformat(data["period_start"])
    peak_date = period_start_date + timedelta(days=peak_idx)
    peak_sub = (
        f"{peak_date.day} {_format_rus_month(peak_date)} · максимум периода"
        if total_spent > 0
        else "пока без трат"
    )

    # Slot 2: limit_streak or avg_check
    if data["daily_limit"] > 0 and passed_days > 0:
        # limit_streak
        best_streak = 0
        current_streak = 0
        for spent in daily_spent[:passed_days]:
            if spent <= data["daily_limit"]:
                current_streak += 1
                best_streak = max(best_streak, current_streak)
            else:
                current_streak = 0
        streak_days = best_streak
        slot2 = {
            "id": "limit_streak",
            "color": accent_green,
            "title": "СЕРИЯ В ЛИМИТЕ",
            "value": f"{streak_days} {_plural_ru(streak_days, ('день подряд', 'дня подряд', 'дней подряд'))}",
            "subtitle": "без пробоя дневного плана",
        }
    else:
        # avg_check
        slot2 = {
            "id": "avg_check",
            "color": accent_blue,
            "title": "СРЕДНИЙ ЧЕК",
            "value": f"{fmt_money(total_spent / max(expenses_count, 1))} ₽",
            "subtitle": "за одну покупку",
        }

    # Slot 3: candidates
    used_ids = {"peak_day", slot2["id"]}
    slot3 = None

    # Compute metrics for candidates
    cur_spent_weekday = sum(
        spent
        for i, spent in enumerate(daily_spent)
        if (period_start_date + timedelta(days=i)).weekday() < 5
    )
    cur_days_weekday = sum(
        1 for i in range(passed_days) if (period_start_date + timedelta(days=i)).weekday() < 5
    )

    prev_spent_weekday = 0.0
    prev_days_weekday = 0
    if prev_expenses and data.get("prev_period_start"):
        prev_start = _parse_date(data["prev_period_start"])
        prev_by_offset: dict[int, float] = {}
        for e in prev_expenses:
            offset = (_parse_date(e["date"]) - prev_start).days
            if 0 <= offset < passed_days:
                if (prev_start + timedelta(days=offset)).weekday() < 5:
                    prev_by_offset[offset] = prev_by_offset.get(offset, 0.0) + e["amount"]

        prev_spent_weekday = sum(prev_by_offset.values())
        prev_days_weekday = sum(
            1 for i in range(passed_days) if (prev_start + timedelta(days=i)).weekday() < 5
        )

    weekday_delta = 0
    if cur_days_weekday > 0 and prev_days_weekday > 0 and prev_spent_weekday > 0:
        weekday_delta = int(
            round(
                (
                    1
                    - (cur_spent_weekday / cur_days_weekday)
                    / (prev_spent_weekday / prev_days_weekday)
                )
                * 100
            )
        )
    weekday_value = (
        f"−{weekday_delta}% в будни" if weekday_delta >= 0 else f"+{abs(weekday_delta)}% в будни"
    )

    prev_sum = sum(e["amount"] for e in prev_expenses) if prev_expenses else 0.0
    month_pace_cand = None
    if total_spent > 0 and prev_income > 0 and current_income > 0 and prev_sum > 0:
        pace_ratio = (total_spent / current_income) / (prev_sum / prev_income) * 100
        month_pace_cand = {
            "id": "month_pace",
            "color": accent_blue,
            "title": "ТЕМП МЕСЯЦА",
            "value": f"{int(round(pace_ratio))}%",
            "subtitle": (
                "быстрее прошлого цикла" if pace_ratio > 100 else "спокойнее прошлого цикла"
            ),
        }

    candidates = [
        (
            "top3_days",
            total_spent > 0 and passed_days >= 5,
            {
                "id": "top3_days",
                "color": accent_amber,
                "title": "3 ДНЯ СДЕЛАЛИ КАССУ",
                "value": f"{int(sum(sorted(daily_spent, reverse=True)[:3]) / max(total_spent, 1) * 100)}%",
                "subtitle": f"остальные {passed_days - 3} дн. прошли ровно"
                if passed_days >= 5
                else "",
            },
        ),
        (
            "weekend_tax",
            total_spent > 0,
            {
                "id": "weekend_tax",
                "color": accent_purple,
                "title": "НАЛОГ НА ВЫХОДНЫЕ",
                "value": f"{int(sum(s for i, s in enumerate(daily_spent) if (period_start_date + timedelta(days=i)).weekday() >= 5) / max(total_spent, 1) * 100)}%",
                "subtitle": "ушло в субботу и воскресенье",
            },
        ),
        (
            "night_food",
            len(expenses) > 0,
            {
                "id": "night_food",
                "color": accent_blue,
                "title": "НОЧНОЙ ДОЖОР",
                "value": f"{fmt_money(sum(e['amount'] for e in expenses if _expense_hour(e) >= 21 or _expense_hour(e) < 5))} ₽",
                "subtitle": "куплено после 21:00",
            },
        ),
        (
            "latte_effect",
            expenses_count >= 5,
            {
                "id": "latte_effect",
                "color": accent_pink,
                "title": "ЭФФЕКТ ЛАТТЕ",
                "value": f"{fmt_money(sum(e['amount'] for e in expenses if e['amount'] <= 1000))} ₽",
                "subtitle": "мелочёвка чеками до 1 000 ₽",
            },
        ),
        (
            "weekday_saving",
            total_spent > 0 and weekday_delta != 0,
            {
                "id": "weekday_saving",
                "color": accent_green,
                "title": "ЭНЕРГОСБЕРЕЖЕНИЕ",
                "value": weekday_value,
                "subtitle": "тише прошлого цикла"
                if weekday_delta >= 0
                else "громче прошлого цикла",
            },
        ),
    ]
    if month_pace_cand:
        candidates.append(("month_pace", True, month_pace_cand))
    candidates.extend(
        [
            (
                "quiet_mode",
                True,
                {
                    "id": "quiet_mode",
                    "color": "#8A99A8",
                    "title": "РЕЖИМ ТИШИНЫ",
                    "value": f"{expenses_count} покупок",
                    "subtitle": "кошелёк отдыхает",
                },
            ),
        ]
    )

    for cand_id, cond, cand in candidates:
        if cand_id not in used_ids and cond:
            slot3 = cand
            break

    if slot3 is None:
        slot3 = {
            "id": "quiet_mode",
            "color": "#8A99A8",
            "title": "РЕЖИМ ТИШИНЫ",
            "value": "0 покупок",
            "subtitle": "кошелёк полностью отдыхает",
        }

    insights = [
        {
            "color": accent_coral,
            "title": "ДОРОГОЙ ДЕНЬ",
            "value": f"{fmt_money(peak_day)} ₽",
            "subtitle": peak_sub,
            "id": "peak_day",
        },
        slot2,
        slot3,
    ]

    # ─── Draw insight cards ───
    for i, ins in enumerate(insights):
        x = 36 + i * (card_w + gap)
        y = insight_y
        # Card background
        draw_rounded_rect((x, y, x + card_w, y + insight_h), 20, "#131C26", "#242F3D", 1)

        # Indicator dot
        dot_x = x + 18
        dot_y = y + 18
        draw.ellipse([dot_x, dot_y, dot_x + 10, dot_y + 10], fill=ins["color"])

        # Title
        draw.text((dot_x + 16, dot_y - 2), ins["title"], font=font_sub, fill=text_secondary)

        # Value
        draw.text((x + 18, y + 52), ins["value"], font=font_metric, fill="#F5F5F5")

        # Subtitle (with wrapping)
        sub_lines = _wrap_text(draw, ins["subtitle"], _load_font("regular", 14), card_w - 36)
        for li, line in enumerate(sub_lines[:2]):
            draw.text(
                (x + 18, y + 96 + li * 20),
                line,
                font=_load_font("regular", 14),
                fill=text_secondary,
            )

    # ════════════════════════════════════════════════════════════════════
    # Save
    # ═══════════════════════════════════════════════════════════════════
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
