import calendar
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
from ..utils.helpers import get_msk_now

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
    year, month = map(int, budget.month.split("-"))
    start_day = budget.period_start_day or 1
    max_day = calendar.monthrange(year, month)[1]
    clamped_start = min(start_day, max_day)
    period_start = datetime(year, month, clamped_start)

    if start_day == 1:
        next_month = month + 1
        next_year = year
        if next_month > 12:
            next_month = 1
            next_year += 1
        period_end = datetime(next_year, next_month, 1) - timedelta(seconds=1)
    else:
        next_month = month + 1
        next_year = year
        if next_month > 12:
            next_month = 1
            next_year += 1
        max_day_next = calendar.monthrange(next_year, next_month)[1]
        clamped_end = min(start_day - 1, max_day_next)
        period_end = datetime(next_year, next_month, clamped_end, 23, 59, 59)

    return period_start, period_end


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
    results: list[tuple[str | None, int, float]] = [
        (row.name, row[2], float(row[3]) if row[3] else 0.0) for row in rows
    ]
    if uncategorized_result:
        cat_name, count, amount = uncategorized_result
        results.append((cat_name, count, amount))
    return results


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
            .where(Expense.category_id == None)
        )
        row = result.one()
        count = row[0] or 0
        total = float(row[1]) if row[1] else 0.0
        if count == 0:
            return None
        return "Без категории", count, total


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
            .where(Expense.category_id != None)
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


def _zone_for_period(
    total_spent: float, total_income: float, mandatory: float, black_day: float
) -> tuple[str, str]:
    available = total_income - mandatory - black_day
    if available <= 0:
        return "⚪", "Нет данных"
    pct = total_spent / available * 100
    if pct <= 70:
        return "🟢", "Зелёная"
    elif pct <= 90:
        return "🔵", "Синяя"
    elif pct <= 100:
        return "🟡", "Жёлтая"
    else:
        return "🔴", "Красная"


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
        header_text += f" ({period_start.strftime('%B').lower()} в процессе ⏳)"

    parts: list[str] = [f"<h2>📊 Итог за {_esc(header_text)}</h2>"]

    if active:
        egg = phrases.MONTHLY_EGG_TOTEM.format(
            period=period_start.strftime("%B").lower(),
            top_cat=data["top_cat_name"],
            totem_name=data["totem_name"],
        )
        parts.append(f"<p>{_esc(egg)}</p>")
    else:
        totem_line = (
            f"<p>{data['totem_emoji']} <b>{_esc(data['totem_name'])}</b>"
            f" — {_esc(data['totem_phrase'])}</p>"
        )
        parts.append(totem_line)

    parts.append("<hr>")

    zone_str = phrases.MONTHLY_ZONE_TAG.format(
        zone_emoji=data["zone_emoji"], zone_label=data["zone_label"]
    )
    parts.append(f"<p><b>💰 Всего потрачено: {data['total_spent']:,.0f} ₽</b> ({zone_str})</p>")

    budget_income = int(budget.total_income)
    parts.append(f"<p>💵 Бюджет: {budget_income:,} ₽</p>")

    avg_line = phrases.MONTHLY_AVG_DAY.format(avg=data["avg_day"])
    parts.append(f"<p>{_esc(avg_line)}</p>")

    if data["breakdown"]:
        parts.append("<h3>📑 Топ расходов по категориям:</h3>")
        parts.append("<table bordered striped>")
        parts.append("  <caption>Распределение трат за период</caption>")
        parts.append("  <tr>")
        parts.append('    <th align="left">Категория</th>')
        parts.append('    <th align="center">Операций</th>')
        parts.append('    <th align="right">Сумма</th>')
        parts.append("  </tr>")
        for cat_name, count, amount in data["breakdown"]:
            clean_name = _esc(cat_name or "Прочее")
            parts.append("  <tr>")
            parts.append(f"    <td>{clean_name}</td>")
            parts.append(f'    <td align="center">{count}</td>')
            parts.append(f'    <td align="right">{int(amount):,} ₽</td>')
            parts.append("  </tr>")
        parts.append("</table>")

        parts.append("<hr>")
        parts.append(f"<p><b>Итого: {int(data['total_spent']):,} ₽</b></p>")

        if data["rounding_total"] > 0:
            parts.append(f"<p>🐸 Округления за период: +{data['rounding_total']:,.0f} ₽</p>")

    details = phrases.MONTHLY_DETAILS.format(
        daily_limit=int(budget.daily_limit),
        rounding_total=int(data["rounding_total"]),
        black_day=int(data["bdf_amount"]),
        black_day_used=int(data["bdf_used"]),
        wishlist_current=int(data["wishlist_current"]),
        wishlist_target=int(data["wishlist_target"]),
        mandatory=int(budget.mandatory_payments),
    )

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
    det_html = det_html.rstrip("<br>")

    period_label = data.get("period_label", "")
    if period_label:
        det_html = f"• Период: {_esc(period_label)}<br>" + det_html
    parts.append("<details>\n<summary>📁 Детали расчёта</summary>\n" + det_html + "\n</details>")

    return "\n".join(parts)


async def build_summary_data(telegram_id: int, budget: Budget) -> dict:
    period_start, period_end = get_period_dates(budget)
    active = is_period_active(budget)
    breakdown = await get_category_breakdown(telegram_id, period_start, period_end)
    total_spent = sum(amount for _, _, amount in breakdown) if breakdown else 0.0
    avg_day = total_spent / 30 if total_spent > 0 else 0.0

    zone_emoji, zone_label = _zone_for_period(
        total_spent, budget.total_income, budget.mandatory_payments, budget.black_day_fund
    )

    top_cat_name = breakdown[0][0] if breakdown else "—"
    totem_name, totem_phrase, totem_emoji = get_totem(top_cat_name or "Прочее")
    if totem_name == "Чебурашка":
        totem_phrase = totem_phrase.format(category=top_cat_name or "Прочее")

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
        "zone_emoji": zone_emoji,
        "zone_label": zone_label,
        "top_cat_name": top_cat_name or "—",
        "totem_name": totem_name,
        "totem_phrase": totem_phrase,
        "totem_emoji": totem_emoji,
        "wishlist_current": wishlist_current,
        "wishlist_target": wishlist_target,
        "bdf_amount": bdf_amount,
        "bdf_used": bdf_used,
        "rounding_total": rounding_total,
        "period_label": f"{period_start.strftime('%d %b').lower()} – {period_end.strftime('%d %b %Y').lower()}",
    }
