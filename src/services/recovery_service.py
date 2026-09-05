from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from ..utils.helpers import get_msk_now

from sqlalchemy import select

from ..db.database import async_session_maker
from ..db.models.models import RecoveryOfferState, RecoveryState


@dataclass(frozen=True)
class RecoveryOption:
    target: Decimal
    days: int
    tail_days: int
    level: str


def _to_decimal(v: float | int | str | Decimal) -> Decimal:
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def calculate_recovery_days(
    deficit: float | Decimal,
    baseline: float | Decimal,
    target: float | Decimal,
) -> int | None:
    d = _to_decimal(deficit)
    b = _to_decimal(baseline)
    t = _to_decimal(target)
    if d <= 0:
        return None
    saving = b - t
    if saving <= 0:
        return None
    days = (d / saving).to_integral_value(rounding=ROUND_CEILING)
    return int(days)


def calculate_recovery_options(
    baseline: float | Decimal,
    money_for_life: float | Decimal,
    days_remaining: int,
    *,
    trigger_ratio: float | Decimal = Decimal("0.85"),
    fast_ratio: float | Decimal = Decimal("0.60"),
    balanced_ratio: float | Decimal = Decimal("0.70"),
    soft_ratio: float | Decimal = Decimal("0.80"),
    min_tail_days: int = 7,
    min_base_limit: float | Decimal = Decimal("1000"),
) -> list[RecoveryOption]:
    b = _to_decimal(baseline)
    m = _to_decimal(money_for_life)
    if b < _to_decimal(min_base_limit) or b == 0:
        return []
    if days_remaining <= 0:
        return []
    dl_pred = m / _to_decimal(days_remaining) if days_remaining else m
    if dl_pred > b * _to_decimal(trigger_ratio):
        return []
    deficit = b * _to_decimal(days_remaining) - m
    if deficit <= 0:
        return []
    levels = [
        ("fast", _to_decimal(fast_ratio)),
        ("balanced", _to_decimal(balanced_ratio)),
        ("soft", _to_decimal(soft_ratio)),
    ]
    options: list[RecoveryOption] = []
    for level, ratio in levels:
        target = (b * ratio).quantize(Decimal("1"))
        days = calculate_recovery_days(deficit, b, target)
        if days is None:
            continue
        if days + min_tail_days <= days_remaining:
            tail = days_remaining - days
            options.append(RecoveryOption(target=target, days=days, tail_days=tail, level=level))
    return options


def should_offer_recovery(
    baseline: float | Decimal,
    money_for_life: float | Decimal,
    days_remaining: int,
    has_active: bool,
    deficit: float | Decimal | None = None,
    *,
    trigger_ratio: float | Decimal = Decimal("0.85"),
    min_base_limit: float | Decimal = Decimal("1000"),
) -> bool:
    b = _to_decimal(baseline)
    m = _to_decimal(money_for_life)
    if has_active:
        return False
    if b < _to_decimal(min_base_limit) or b == 0:
        return False
    if days_remaining <= 0:
        return False
    dl_pred = m / _to_decimal(days_remaining) if days_remaining else m
    if dl_pred > b * _to_decimal(trigger_ratio):
        return False
    d = _to_decimal(deficit) if deficit is not None else (b * _to_decimal(days_remaining) - m)
    if d <= 0:
        return False
    opts = calculate_recovery_options(
        b, m, days_remaining, trigger_ratio=trigger_ratio, min_base_limit=min_base_limit
    )
    return len(opts) > 0


def check_success(
    dl_pred: float | Decimal,
    baseline: float | Decimal,
    success_ratio: float | Decimal = Decimal("0.90"),
) -> bool:
    return _to_decimal(dl_pred) >= _to_decimal(baseline) * _to_decimal(success_ratio)


def is_small_overspend(
    spent: float | Decimal,
    target: float | Decimal,
    ratio: float | Decimal = Decimal("1.10"),
) -> bool:
    return _to_decimal(spent) <= _to_decimal(target) * _to_decimal(ratio)


def is_significant_worsening(
    new_target: float | Decimal,
    old_target: float | Decimal,
    threshold: float | Decimal = Decimal("0.90"),
) -> bool:
    return _to_decimal(new_target) <= _to_decimal(old_target) * _to_decimal(threshold)


def recalculate_days(
    deficit: float | Decimal,
    baseline: float | Decimal,
    target: float | Decimal,
) -> int | None:
    return calculate_recovery_days(deficit, baseline, target)


def should_repeat_offer(
    last_offer_deficit: float | Decimal | None,
    current_deficit: float | Decimal,
    baseline: float | Decimal,
    days_since_offer: int,
    cooldown_days: int = 3,
    repeat_mult: float | Decimal = Decimal("0.50"),
) -> bool:
    if last_offer_deficit is None:
        return True
    if days_since_offer >= cooldown_days:
        return True
    b = _to_decimal(baseline)
    last = _to_decimal(last_offer_deficit)
    cur = _to_decimal(current_deficit)
    return cur >= last + b * _to_decimal(repeat_mult)


async def get_active_recovery(telegram_id: int) -> RecoveryState | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(RecoveryState)
            .where(RecoveryState.telegram_id == telegram_id, RecoveryState.status == "active")
            .order_by(RecoveryState.started_at.desc())
        )
        return result.scalars().first()


async def get_offer_state(telegram_id: int) -> RecoveryOfferState | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(RecoveryOfferState).where(RecoveryOfferState.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()


async def dismiss_offer(telegram_id: int, deficit: float | Decimal) -> None:
    now = get_msk_now()
    async with async_session_maker() as session:
        result = await session.execute(
            select(RecoveryOfferState).where(RecoveryOfferState.telegram_id == telegram_id)
        )
        state = result.scalar_one_or_none()
        if state:
            state.dismissed = True
            state.last_offer_at = now
            state.last_offer_deficit = float(deficit)
        else:
            state = RecoveryOfferState(
                telegram_id=telegram_id,
                dismissed=True,
                last_offer_at=now,
                last_offer_deficit=float(deficit),
            )
            session.add(state)
        await session.commit()


async def create_recovery(
    telegram_id: int,
    budget_id: int,
    baseline: float | Decimal,
    target: float | Decimal,
    total_days: int,
    deficit: float | Decimal,
) -> RecoveryState:
    now = get_msk_now()
    b = float(_to_decimal(baseline))
    t = float(_to_decimal(target))
    d = float(_to_decimal(deficit))
    async with async_session_maker() as session:
        rs = RecoveryState(
            telegram_id=telegram_id,
            budget_id=budget_id,
            status="active",
            baseline=b,
            target=t,
            total_days=total_days,
            initial_deficit=d,
            initial_target=t,
            initial_total_days=total_days,
            started_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(rs)
        await session.commit()
        await session.refresh(rs)
        return rs


async def stop_recovery(telegram_id: int) -> RecoveryState | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(RecoveryState)
            .where(RecoveryState.telegram_id == telegram_id, RecoveryState.status == "active")
            .order_by(RecoveryState.started_at.desc())
        )
        rs = result.scalars().first()
        if not rs:
            return None
        rs.status = "stopped"
        rs.stopped_at = get_msk_now()
        rs.updated_at = get_msk_now()
        await session.commit()
        return rs


async def complete_recovery(telegram_id: int, reason: str) -> RecoveryState | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(RecoveryState)
            .where(RecoveryState.telegram_id == telegram_id, RecoveryState.status == "active")
            .order_by(RecoveryState.started_at.desc())
        )
        rs = result.scalars().first()
        if not rs:
            return None
        rs.status = "completed" if reason != "period_end" else "expired"
        rs.completion_reason = reason
        rs.completed_at = get_msk_now()
        rs.updated_at = get_msk_now()
        await session.commit()
        return rs


async def update_recovery_days(telegram_id: int, new_days: int) -> RecoveryState | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(RecoveryState)
            .where(RecoveryState.telegram_id == telegram_id, RecoveryState.status == "active")
            .order_by(RecoveryState.started_at.desc())
        )
        rs = result.scalars().first()
        if not rs:
            return None
        if rs.total_days != new_days:
            rs.total_days = new_days
            rs.updated_at = get_msk_now()
            await session.commit()
        return rs


async def expire_active_recoveries_for_budget(budget_id: int) -> None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(RecoveryState).where(
                RecoveryState.budget_id == budget_id, RecoveryState.status == "active"
            )
        )
        for rs in result.scalars().all():
            rs.status = "expired"
            rs.completion_reason = "period_end"
            rs.completed_at = get_msk_now()
            rs.updated_at = get_msk_now()
        await session.commit()
