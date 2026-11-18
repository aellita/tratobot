from datetime import datetime, timedelta

from sqlalchemy import func, select

from ..db.database import async_session_maker
from ..db.models.models import (
    BlackDayFund,
    Budget,
    Category,
    Expense,
    UserSettings,
    Wishlist,
)
from ..utils import phrases
from ..utils.helpers import get_msk_now, period_total_days

TOTEM_MAP: list[tuple[list[str], str, str, str]] = [
    (
        ["транспорт", "активности", "такси", "билеты"],
        "Лягушка-путешественница",
        "🐸",
        phrases.MONTHLY_TOTEM_TRAVEL,
    ),
    (["еда", "кафе", "ресторан", "доставка"], "Винни-Пух", "🍯", phrases.MONTHLY_TOTEM_FOOD),
    (["покупки", "одежда", "шопинг"], "Золушка", "✨", phrases.MONTHLY_TOTEM_SHOPPING),
    (["развлечения", "гэс-2", "кино", "театр"], "Кот Леопольд", "🎨", phrases.MONTHLY_TOTEM_FUN),
    (["здоровье", "спорт", "красота", "аптека"], "Дядя Стёпа", "🏋️", phrases.MONTHLY_TOTEM_HEALTH),
    (["дом", "подписки", "жкх"], "Домовёнок Кузя", "🏡", phrases.MONTHLY_TOTEM_HOME),
]


def get_totem(category_name: str) -> tuple[str, str, str]:
    cat_lower = category_name.lower().strip()
    for triggers, name, emoji, phrase in TOTEM_MAP:
        for trigger in triggers:
            if trigger in cat_lower:
                return name, phrase, emoji
    return "Чебурашка", phrases.MONTHLY_TOTEM_DEFAULT, "🍊"


def get_period_dates(budget: Budget) -> tuple[datetime, datetime]:
    from ..utils.helpers import period_dates

    return period_dates(budget.month, budget.period_start_day or 1)


def is_period_active(budget: Budget) -> bool:
    today = get_msk_now()
    start = budget.period_start_day or 1
    this_month = today.strftime("%Y-%m")
    last_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    if today.day >= start and budget.month == this_month:
        return True
    if today.day < start and budget.month == last_month:
        return True
    return False


def compute_avg_day(
    total_spent: float,
    period_start: datetime,
    total_days: int,
    active: bool,
    today: datetime,
) -> float:
    """Средний расход в день: от фактической длины периода, не от 30."""
    if total_spent <= 0:
        return 0.0

    if active:
        elapsed = (today.date() - period_start.date()).days + 1
        days = max(1, min(elapsed, total_days))
    else:
        days = max(1, total_days)

    return total_spent / days


async def get_all_budgets(telegram_id: int) -> list[Budget]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Budget).where(Budget.telegram_id == telegram_id).order_by(Budget.month.desc())
        )
        return list(result.scalars().all())


async def get_average_expenses(telegram_id: int) -> float:
    budgets = await get_all_budgets(telegram_id)
    if not budgets:
        return 0.0
    totals: list[float] = []
    for budget in budgets:
        if is_period_active(budget):
            continue
        period_start, period_end = get_period_dates(budget)
        breakdown = await get_category_breakdown(telegram_id, period_start, period_end)
        total = sum(amount for _, _, amount in breakdown)
        if total > 0:
            totals.append(total)
    if not totals:
        return 0.0
    return sum(totals) / len(totals)


async def get_category_breakdown(
    telegram_id: int, period_start: datetime, period_end: datetime
) -> list[tuple[str | None, int, float]]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Category.id, Category.name, func.count(Expense.id), func.sum(Expense.amount))
            .join(Expense, Expense.category_id == Category.id)
            .where(Expense.telegram_id == telegram_id)
            .where(Expense.date >= period_start)
            .where(Expense.date <= period_end)
            .where(Expense.is_deleted == False)
            .group_by(Category.id)
            .order_by(func.sum(Expense.amount).desc().nullslast())
        )
        rows = result.all()

    uncategorized_result = await _get_uncategorized_sum(telegram_id, period_start, period_end)

    # Build dict: name -> (count, amount), merge "Без категории" if real category exists
    merged: dict[str, tuple[int, float]] = {}
    for row in rows:
        name = row.name
        count = row[2]
        amount = float(row[3]) if row[3] else 0.0
        merged[name] = (count, amount)

    if uncategorized_result:
        cat_name, count, amount = uncategorized_result
        if cat_name in merged:
            old_count, old_amount = merged[cat_name]
            merged[cat_name] = (old_count + count, old_amount + amount)
        else:
            merged[cat_name] = (count, amount)

    # Sort by amount desc, then count desc
    sorted_items = sorted(
        merged.items(),
        key=lambda x: (x[1][1], x[1][0]),
        reverse=True,
    )
    return [(name, count, amount) for name, (count, amount) in sorted_items]


async def _get_uncategorized_sum(
    telegram_id: int, period_start: datetime, period_end: datetime
) -> tuple[str, int, float] | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(func.count(Expense.id), func.sum(Expense.amount))
            .where(Expense.telegram_id == telegram_id)
            .where(Expense.date >= period_start)
            .where(Expense.date <= period_end)
            .where(Expense.is_deleted == False)
            .where(Expense.category_id == None)  # noqa: E711 — SQLAlchemy IS NULL
        )
        row = result.one()
        count = row[0] or 0
        total = float(row[1]) if row[1] else 0.0
        if count == 0:
            return None
        return phrases.MONTHLY_NO_CATEGORY, count, total


async def _get_active_wishlist(telegram_id: int) -> Wishlist | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Wishlist).where(Wishlist.telegram_id == telegram_id, Wishlist.is_active == True)
        )
        return result.scalar_one_or_none()


async def _get_black_day_fund_data(telegram_id: int, month: str) -> tuple[float, float]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(BlackDayFund).where(
                BlackDayFund.telegram_id == telegram_id, BlackDayFund.month == month
            )
        )
        bdf = result.scalar_one_or_none()
        if bdf:
            return bdf.amount, bdf.used_amount
        return 0.0, 0.0


async def _get_rounding_total(
    telegram_id: int, period_start: datetime, period_end: datetime
) -> float:
    async with async_session_maker() as session:
        result = await session.execute(
            select(UserSettings).where(UserSettings.telegram_id == telegram_id)
        )
        settings = result.scalar_one_or_none()
    if not settings or settings.rounding_mode == 0:
        return 0.0

    async with async_session_maker() as session:
        result = await session.execute(
            select(func.sum(Expense.amount))
            .where(Expense.telegram_id == telegram_id)
            .where(Expense.date >= period_start)
            .where(Expense.date <= period_end)
            .where(Expense.is_deleted == False)
            .where(Expense.category_id != None)  # noqa: E711 — SQLAlchemy IS NOT NULL
        )
        raw = float(result.scalar() or 0.0)

    mode = settings.rounding_mode
    unrounded = (raw // mode) * mode
    return raw - unrounded


async def get_period_label(budget: Budget) -> str:
    period_start, period_end = get_period_dates(budget)
    start_str = period_start.strftime("%d %b").lower()
    end_str = period_end.strftime("%d %b %Y").lower()
    return f"{start_str} – {end_str}"


def compute_saved_state(available: float, spent: float) -> tuple[int, str]:
    """Ветка «Сэкономлено/Перерасход» по доступной базе периода.

    Округление считается до выбора ветки: иначе при 49 999.60 ₽ остатка
    получилось бы «Сэкономлено 0 ₽» с тоном «впритык».
    """
    if available <= 0:
        return 0, "no_limit"

    saved = round(available - spent)
    if saved > 0:
        pct = spent / available * 100
        if pct <= 70:
            return saved, "green"
        if pct <= 90:
            return saved, "blue"
        return saved, "yellow"
    if saved == 0:
        return 0, "zero"
    return saved, "overrun"


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def format_summary_text(data: dict, label: str = "") -> str:
    budget = data["budget"]
    period_start = data["period_start"]
    active = data["active"]

    month_str = period_start.strftime("%B %Y").lower()
    header_text = label or month_str.capitalize()
    if active:
        header_text += phrases.MONTHLY_IN_PROGRESS.format(
            period=period_start.strftime("%B").lower()
        )

    parts: list[str] = [f"<h2>{phrases.MONTHLY_HEADER.format(period_label=_esc(header_text))}</h2>"]

    # Empty period → MONTHLY_EMPTY, no totem
    if not data["breakdown"]:
        parts.append(f"<p>{_esc(phrases.MONTHLY_EMPTY)}</p>")
        parts.append("<hr>")
    else:
        top_cat = data["top_cat_name"]
        is_no_category_top = top_cat == phrases.MONTHLY_NO_CATEGORY

        if active:
            if is_no_category_top:
                egg = phrases.MONTHLY_EGG_TOTEM_NO_CATEGORY.format(
                    period=period_start.strftime("%B").lower()
                )
            else:
                egg = phrases.MONTHLY_EGG_TOTEM.format(
                    period=period_start.strftime("%B").lower(),
                    top_cat=top_cat,
                    totem_name=data["totem_name"],
                )
            parts.append(f"<p>{_esc(egg)}</p>")
        else:
            if is_no_category_top:
                totem_line = f"<p>{_esc(phrases.MONTHLY_TOTEM_NO_CATEGORY)}</p>"
            else:
                totem_line = (
                    f"<p>{data['totem_emoji']} <b>{_esc(data['totem_name'])}</b>"
                    f" — {_esc(data['totem_phrase'])}</p>"
                )
            parts.append(totem_line)

    parts.append("<hr>")

    _total = f"{data['total_spent']:,.0f}"
    parts.append(f"<p><b>💰 {phrases.MONTHLY_TOTAL_SPENT.format(amount=_total)}</b></p>")

    income = float(data.get("income", budget.total_income))
    parts.append(f"<p>{_esc(phrases.MONTHLY_INCOME_LABEL.format(amount=f'{income:,.0f}'))}</p>")

    added_income = float(data.get("added_income", 0) or 0)
    if added_income > 0:
        added_line = phrases.MONTHLY_ADDED_INCOME.format(amount=f"{added_income:,.0f}")
        parts.append(f"<p>{_esc(added_line)}</p>")

    if not active:
        saved = int(data.get("saved", 0))
        tier = data.get("saved_tier")
        if tier == "no_limit":
            fund = float(getattr(budget, "black_day_fund", 0) or 0)
            phrase = phrases.MONTHLY_NO_LIMIT_FUND if fund > 0 else phrases.MONTHLY_NO_LIMIT
            parts.append(f"<p>{_esc(phrase)}</p>")
        elif tier == "overrun":
            overrun = phrases.MONTHLY_OVERRUN.format(amount=f"{abs(saved):,.0f}")
            parts.append(f"<p>{_esc(overrun)}</p>")
        elif tier == "zero":
            parts.append(f"<p>{_esc(phrases.MONTHLY_SAVED_ZERO)}</p>")
        elif tier in ("green", "blue", "yellow"):
            template = {
                "green": phrases.MONTHLY_SAVED_GREEN,
                "blue": phrases.MONTHLY_SAVED_BLUE,
                "yellow": phrases.MONTHLY_SAVED_YELLOW,
            }[tier]
            parts.append(f"<p>{_esc(template.format(amount=f'{saved:,.0f}'))}</p>")

    avg_line = phrases.MONTHLY_AVG_DAY.format(avg=data["avg_day"])
    parts.append(f"<p>{_esc(avg_line)}</p>")

    if data["breakdown"]:
        parts.append(f"<h3>📑 {phrases.MONTHLY_TOP_HEADER}</h3>")
        parts.append("<table bordered striped>")
        parts.append(f"  <caption>{phrases.MONTHLY_TABLE_CAPTION}</caption>")
        parts.append("  <tr>")
        parts.append(f'    <th align="left">{phrases.MONTHLY_TABLE_COL_CATEGORY}</th>')
        parts.append(f'    <th align="center">{phrases.MONTHLY_TABLE_COL_COUNT}</th>')
        parts.append(f'    <th align="right">{phrases.MONTHLY_TABLE_COL_AMOUNT}</th>')
        parts.append("  </tr>")
        for cat_name, count, amount in data["breakdown"]:
            clean_name = _esc(cat_name or phrases.DEFAULT_CATEGORY[1])
            parts.append("  <tr>")
            parts.append(f"    <td>{clean_name}</td>")
            parts.append(f'    <td align="center">{count}</td>')
            parts.append(f'    <td align="right">{int(amount):,} ₽</td>')
            parts.append("  </tr>")
        parts.append("</table>")

        parts.append("<hr>")
        _total2 = f"{int(data['total_spent']):,}"
        parts.append(f"<p><b>{phrases.MONTHLY_TOTAL_LABEL.format(amount=_total2)}</b></p>")

    details = phrases.MONTHLY_DETAILS.format(
        daily_limit=int(budget.daily_limit),
        mandatory=int(budget.mandatory_payments),
    )
    black_day = float(getattr(budget, "black_day_fund", 0) or 0)
    if black_day > 0:
        details += "\n" + phrases.MONTHLY_DETAILS_FUND.format(amount=black_day)

    det_html = ""
    for det_line in details.strip().split("\n"):
        raw = det_line.strip()
        if raw.startswith("• "):
            content = raw[2:]
        else:
            content = raw
        if ":" in content:
            lbl, val = content.split(":", 1)
            det_html += f"• {lbl.strip()}: <code>{_esc(val.strip())}</code><br>"
        else:
            det_html += f"• {_esc(content)}<br>"
    det_html = det_html.removesuffix("<br>")

    period_label = data.get("period_label", "")
    if period_label:
        det_html = (
            f"• {phrases.MONTHLY_PERIOD_LABEL.format(label=_esc(period_label))}<br>" + det_html
        )
    parts.append(
        f"<details>\n<summary>📁 {phrases.MONTHLY_DETAILS_SUMMARY}</summary>\n"
        + det_html
        + "\n</details>"
    )

    return "\n".join(parts)


async def build_summary_data(telegram_id: int, budget: Budget) -> dict:
    period_start, period_end = get_period_dates(budget)
    active = is_period_active(budget)
    breakdown = await get_category_breakdown(telegram_id, period_start, period_end)
    total_spent = sum(amount for _, _, amount in breakdown) if breakdown else 0.0
    total_days = period_total_days(budget.month, budget.period_start_day or 1)
    avg_day = compute_avg_day(total_spent, period_start, total_days, active, get_msk_now())

    available = max(
        float(budget.total_income)
        - float(budget.mandatory_payments)
        - float(budget.black_day_fund),
        0.0,
    )
    saved, saved_tier = compute_saved_state(available, total_spent)

    top_cat_name = breakdown[0][0] if breakdown else "—"
    totem_name, totem_phrase, totem_emoji = get_totem(top_cat_name or phrases.DEFAULT_CATEGORY[1])
    if totem_name == "Чебурашка":
        totem_phrase = totem_phrase.format(category=top_cat_name or phrases.DEFAULT_CATEGORY[1])

    wishlist = await _get_active_wishlist(telegram_id)
    wishlist_current = wishlist.current_amount if wishlist else 0.0
    wishlist_target = wishlist.target_amount if wishlist else 0.0

    bdf_amount, bdf_used = await _get_black_day_fund_data(telegram_id, budget.month)

    rounding_total = await _get_rounding_total(telegram_id, period_start, period_end)

    return {
        "budget": budget,
        "active": active,
        "period_start": period_start,
        "period_end": period_end,
        "breakdown": breakdown,
        "total_spent": total_spent,
        "avg_day": avg_day,
        "available": available,
        "saved": saved,
        "saved_tier": saved_tier,
        "income": float(budget.total_income),
        "added_income": float(getattr(budget, "added_income", 0) or 0),
        "top_cat_name": top_cat_name or "—",
        "totem_name": totem_name,
        "totem_phrase": totem_phrase,
        "totem_emoji": totem_emoji,
        "wishlist_current": wishlist_current,
        "wishlist_target": wishlist_target,
        "bdf_amount": bdf_amount,
        "bdf_used": bdf_used,
        "rounding_total": rounding_total,
        "period_label": (
            f"{period_start.strftime('%d %b').lower()} – {period_end.strftime('%d %b %Y').lower()}"
        ),
    }
