"""Зоны дневного лимита и прогноз — единые правила для статуса и утра."""

from __future__ import annotations

ZONE_GREEN = "green"
ZONE_BLUE = "blue"
ZONE_YELLOW = "yellow"
ZONE_RED = "red"
ZONE_FINISH = "finish"
ZONE_ATAS = "atas"

END_OF_PERIOD_DAYS = 3

# Сжатие сегодняшнего плана относительно базового дневного лимита.
PRESSURE_GREEN_MIN = 90.0
PRESSURE_LIGHT_MIN = 70.0
PRESSURE_NONE_MIN = 26.0

TREND_GREEN = "green"
TREND_LIGHT = "light"
TREND_SQUEEZE = "squeeze"
TREND_NONE = "none"
TREND_OVER = "over"
TREND_DEAD = "dead"


def is_end_of_period(days_left: int) -> bool:
    return days_left <= END_OF_PERIOD_DAYS


def tomorrow_plan(money_for_life: float, days_left: int) -> float:
    """Лимит на завтра: остаток после сегодняшних трат на дни без сегодня."""
    if days_left <= 1:
        return 0.0
    return max(float(money_for_life) / max(days_left - 1, 1), 0)


def limit_pressure_pct(plan_today: float, base_daily_limit: float) -> float:
    """Насколько сегодняшний план сжат относительно базового лимита."""
    if base_daily_limit <= 0:
        return 0.0
    return float(plan_today) / float(base_daily_limit) * 100


def plan_zone(plan_today: float, base_daily_limit: float) -> str:
    """Зона по сжатию плана: 90 / 70 / 26."""
    pct = limit_pressure_pct(plan_today, base_daily_limit)
    if pct >= PRESSURE_GREEN_MIN:
        return ZONE_GREEN
    if pct >= PRESSURE_LIGHT_MIN:
        return ZONE_BLUE
    if pct >= PRESSURE_NONE_MIN:
        return ZONE_YELLOW
    return ZONE_RED


def status_zone(
    *,
    plan_today: float,
    base_daily_limit: float,
    money_for_life: float,
    days_left: int,
) -> str:
    """Зона в шапке статуса.

    Перерасход и нулевой свободный лимит зону не меняют — они влияют
    только на строку дня и футер. В финале периода остаются «Финиш»/«Атас».
    """
    if is_end_of_period(days_left):
        return ZONE_ATAS if money_for_life <= 0 else ZONE_FINISH
    return plan_zone(plan_today, base_daily_limit)


def limit_trend(
    plan_today: float,
    base_daily_limit: float,
    free_today: float,
    overrun_today: float,
) -> str:
    """Тон футера: состояние дня важнее сжатия плана."""
    if overrun_today > 0:
        return TREND_OVER
    if free_today <= 0:
        return TREND_NONE
    pct = limit_pressure_pct(plan_today, base_daily_limit)
    if pct >= PRESSURE_GREEN_MIN:
        return TREND_GREEN
    if pct >= PRESSURE_LIGHT_MIN:
        return TREND_LIGHT
    if pct >= PRESSURE_NONE_MIN:
        return TREND_SQUEEZE
    return TREND_DEAD


def forecast_amount(
    plan_today: float,
    tomorrow_plan_value: float,
    days_left: int,
) -> int | None:
    """Цифру прогноза показываем только при реальном снижении и не в финале."""
    if is_end_of_period(days_left):
        return None
    plan_int = int(round(plan_today))
    tomorrow_int = int(round(tomorrow_plan_value))
    if tomorrow_int >= plan_int:
        return None
    return tomorrow_int
