"""Monthly chart widget: compact data aggregation, state JSON, and inline SVG/JS widget HTML."""

import json
import zlib
from datetime import datetime, timedelta
from typing import TypedDict

from sqlalchemy import func, select

from ..db.database import async_session_maker
from ..db.models.models import Budget, Expense
from ..utils.helpers import get_msk_now, period_dates, period_total_days


class ChartDayData(TypedDict):
    """Compact day data: spent amount only (limit is constant per period)."""
    spent: float


class ChartState(TypedDict):
    """Compact widget state (≤ 1024 bytes).

    Structure:
    {
        "m": "2026-11",      # month prefix
        "s": "2026-11-10",   # period start date (for periods not starting on 1st)
        "d": [0, 1200, 450], # spent per day (float)
        "lim": 5000.0,       # base daily limit
        "a": true            # active period
    }
    """
    m: str      # month prefix "YYYY-MM"
    s: str      # period start date "YYYY-MM-DD"
    d: list[float]  # spent per day
    lim: float    # base daily limit
    a: bool     # active period


def _compute_base_daily_limit(budget: Budget) -> float:
    """Base daily limit = (income - mandatory - black_day_fund) / total_days_in_period."""
    available = (
        float(budget.total_income)
        - float(budget.mandatory_payments)
        - float(budget.black_day_fund)
    )
    if available <= 0:
        return 0.0
    total_days = period_total_days(budget.month, budget.period_start_day or 1)
    return max(available / max(total_days, 1), 0.0)


async def build_chart_data(telegram_id: int, budget: Budget) -> list[ChartDayData]:
    """Aggregate daily spending for the budget period.

    Returns list of ChartDayData for every day in period (including zero-spend days).
    For active period: includes today and past days only.
    """
    period_start, period_end = period_dates(budget.month, budget.period_start_day or 1)
    today = get_msk_now().date()

    # For active period, cap at today
    is_active = budget.month in {
        today.strftime("%Y-%m"),
        (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m"),
    }
    if is_active:
        end_date = min(period_end.date(), today)
    else:
        end_date = period_end.date()

    # Fetch expenses grouped by date
    # Use < next_day_start to include expenses on end_date with any time
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

    # Build array for every day in period (capped at today if active)
    data: list[ChartDayData] = []
    current = period_start.date()
    while current <= end_date:
        day_str = current.isoformat()
        data.append(
            ChartDayData(spent=spent_by_date.get(day_str, 0.0))
        )
        current += timedelta(days=1)

    return data


def build_chart_state(telegram_id: int, budget: Budget, data: list[ChartDayData]) -> ChartState:
    """Build compact chart state JSON for widget (≤ 1024 bytes)."""
    today = get_msk_now().date()
    is_active = budget.month in {
        today.strftime("%Y-%m"),
        (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m"),
    }

    period_start, _ = period_dates(budget.month, budget.period_start_day or 1)
    period_start_str = period_start.strftime("%Y-%m-%d")

    # Compact: month prefix + period start + flat array of spent values
    month_prefix = budget.month  # "YYYY-MM"
    spent_array = [round(d["spent"], 2) for d in data]
    base_limit = _compute_base_daily_limit(budget)

    state = ChartState(
        m=month_prefix,
        s=period_start_str,
        d=spent_array,
        lim=round(base_limit, 2),
        a=is_active,
    )

    # Validate size
    json_str = json.dumps(state, separators=(",", ":"))
    if len(json_str.encode("utf-8")) > 1024:
        raise ValueError(f"Chart state exceeds 1024 bytes: {len(json_str)}")

    return state


# Inline SVG/JS widget HTML (≤ 4096 bytes after zlib)
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

  // Find max for Y scale
  let maxVal = baseLimit;
  for (const v of days) { if (v > maxVal) maxVal = v; }
  maxVal = Math.max(maxVal, 1) * 1.15;

  const yScale = v => padding.top + innerH * (1 - v / maxVal);
  const xScale = i => padding.left + i * (innerW / n) + (innerW / n - barW) / 2;

  // Build SVG
  let svgHTML = '';
  // Y axis
  svgHTML += `<line class="axis" x1="${padding.left}" y1="${padding.top}" x2="${padding.left}" y2="${padding.top + innerH}"/>`;
  // X axis
  svgHTML += `<line class="axis" x1="${padding.left}" y1="${padding.top + innerH}" x2="${w - padding.right}" y2="${padding.top + innerH}"/>`;
  // Limit line
  if (baseLimit > 0) {
    const ly = yScale(baseLimit);
    svgHTML += `<line class="limit-line" x1="${padding.left}" y1="${ly}" x2="${w - padding.right}" y2="${ly}"/>`;
    svgHTML += `<text x="${padding.left - 4}" y="${ly - 2}" text-anchor="end" font-size="8" fill="var(--tg-theme-hint-color, #999999)">${fmt(baseLimit)}</text>`;
  }
  // Bars
  for (let i = 0; i < n; i++) {
    const spent = days[i];
    const x = xScale(i);
    const barH = innerH * (spent / maxVal);
    const y = yScale(spent);
    const cls = spent > baseLimit && baseLimit > 0 ? 'bar bar-over' : 'bar bar-ok';
    const sel = i === selectedIndex ? ' selected' : '';
    svgHTML += `<rect class="${cls}${sel}" x="${x}" y="${y}" width="${barW}" height="${barH}" data-index="${i}" rx="1"/>`;
    // Invisible tall hit area
    svgHTML += `<rect class="bar" fill="transparent" x="${x}" y="${padding.top}" width="${barW}" height="${innerH}" data-index="${i}"/>`;
  }
  // X ticks (max 6 ticks)
  const step = Math.max(1, Math.ceil(n / 6));
  for (let i = 0; i < n; i += step) {
    const x = padding.left + (i + 0.5) * (innerW / n);
    const cls = i === selectedIndex ? 'tick selected-tick' : 'tick';
    svgHTML += `<g class="${cls}"><line x1="${x}" y1="${padding.top + innerH}" x2="${x}" y2="${padding.top + innerH + 4}"/><text x="${x}" y="${padding.top + innerH + 14}" text-anchor="middle">${formatDate(i)}</text></g>`;
  }
  // Last day
  if (n - 1 > 0 && (n - 1) % step !== 0) {
    const x = padding.left + (n - 0.5) * (innerW / n);
    svgHTML += `<g class="tick"><line x1="${x}" y1="${padding.top + innerH}" x2="${x}" y2="${padding.top + innerH + 4}"/><text x="${x}" y="${padding.top + innerH + 14}" text-anchor="middle">${formatDate(n - 1)}</text></g>`;
  }

  svg.innerHTML = svgHTML;
  caption.textContent = `📊 Траты по дням · ${state.m} (${n} дн.)`;

  // Tooltip handlers
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

  // Position tooltip above bar with clamping
  const rect = svg.querySelector(`[data-index="${idx}"].bar-over, [data-index="${idx}"].bar-ok`);
  if (rect) {
    const svgRect = svg.getBoundingClientRect();
    const barRect = rect.getBoundingClientRect();
    let left = barRect.left - svgRect.left + rect.width.baseVal.value / 2;
    let top = barRect.top - svgRect.top - 4;

    // Clamp horizontal: keep tooltip within [55, w - 55]
    left = Math.max(55, Math.min(w - 55, left));

    // Clamp vertical: if bar is tall and tooltip would be cut off at top, show below bar
    if (top < 42) {
      top = barRect.top - svgRect.top + barH + 8;
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

// Load state from chatData
widget.on('chatDataChanged', data => {
  if (data && data.d) {
    state = data;
    selectedIndex = -1;
    tooltip.classList.remove('visible');
    hint.textContent = 'Нажми на день, чтобы увидеть детали';
    render();
  }
});

</script>
</html>
"""


def validate_widget_html() -> bool:
    """Validate widget HTML size constraint (≤ 4096 bytes after zlib)."""
    compressed = zlib.compress(CHART_WIDGET_HTML.encode("utf-8"))
    return len(compressed) <= 4096


# Validate on import
assert validate_widget_html(), "Widget HTML exceeds 4096 bytes after zlib compression"
