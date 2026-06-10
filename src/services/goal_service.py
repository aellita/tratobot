from sqlalchemy import select

from ..db.database import async_session_maker
from ..db.models.models import Budget, Wishlist
from ..utils.helpers import get_msk_now


async def get_active_goal(telegram_id: int) -> Wishlist | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Wishlist)
            .where(Wishlist.telegram_id == telegram_id, Wishlist.is_active == True)
            .order_by(Wishlist.id)
            .limit(1)
        )
        return result.scalar_one_or_none()


async def get_goal_current_amount(telegram_id: int) -> float:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Wishlist.current_amount)
            .where(Wishlist.telegram_id == telegram_id, Wishlist.is_active == True)
            .order_by(Wishlist.id)
            .limit(1)
        )
        return float(result.scalar() or 0.0)


async def add_spare_change_to_goal(telegram_id: int, spare_change: float) -> tuple[float, str]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Wishlist)
            .where(Wishlist.telegram_id == telegram_id, Wishlist.is_active == True)
            .order_by(Wishlist.id)
            .limit(1)
        )
        goal = result.scalar_one_or_none()

        if not goal:
            month = get_msk_now().strftime("%Y-%m")
            budget_result = await session.execute(
                select(Budget).where(
                    Budget.telegram_id == telegram_id,
                    Budget.month == month,
                )
            )
            budget = budget_result.scalar_one_or_none()
            name = budget.wishlist_name if budget else "Хотелка"
            target = budget.wishlist_target if budget else 0

            goal = Wishlist(
                telegram_id=telegram_id,
                name=name,
                target_amount=target,
                current_amount=0,
            )
            session.add(goal)
            await session.flush()

        goal.current_amount += spare_change
        await session.commit()
        return goal.current_amount, goal.name


async def deduct_from_goal(telegram_id: int, amount: float) -> tuple[float, float, str] | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Wishlist)
            .where(Wishlist.telegram_id == telegram_id, Wishlist.is_active == True)
            .order_by(Wishlist.id)
            .limit(1)
        )
        goal = result.scalar_one_or_none()
        if not goal or goal.current_amount <= 0:
            return None

        deduction = min(amount, goal.current_amount)
        goal.current_amount -= deduction
        await session.commit()
        return deduction, goal.current_amount, goal.name
