import logging

from aiogram import BaseMiddleware, Bot, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ...core.config import settings
from ...services.evening_report import EVENING_KB, INITIAL_TEXT, EveningState, send_evening_teaser
from ...services.morning_report import send_morning_reports
from ...utils import phrases

logger = logging.getLogger(__name__)

router = Router()


class AdminOnlyMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user is None or user.id not in settings.admin_ids:
            logger.warning("Denied test command from %s", user.id if user else None)
            return None
        return await handler(event, data)


router.message.middleware(AdminOnlyMiddleware())


def _is_admin(message: Message) -> bool:
    user = message.from_user
    return user is not None and user.id in settings.admin_ids


@router.message(Command("test_evening"))
async def cmd_test_evening(message: Message, state: FSMContext):
    if not _is_admin(message):
        return
    msg = await message.answer(INITIAL_TEXT, reply_markup=EVENING_KB)
    await state.set_state(EveningState.filling)
    await state.update_data(container_id=msg.message_id, session_expenses=[])


@router.message(Command("test_teaser"))
async def cmd_test_teaser(message: Message, bot: Bot, state: FSMContext):
    if not _is_admin(message):
        return
    await message.answer(phrases.TEST_TEASER_START)
    sent = await send_evening_teaser(bot, state.storage, user_ids=[message.from_user.id])
    await message.answer(phrases.TEST_TEASER_SENT if sent else phrases.TEST_TEASER_SKIPPED)


@router.message(Command("test_morning"))
async def cmd_test_morning(message: Message, bot: Bot):
    if not _is_admin(message):
        return
    await message.answer(phrases.TEST_MORNING_START)
    sent = await send_morning_reports(bot, user_ids=[message.from_user.id], force=True)
    await message.answer(phrases.TEST_MORNING_SENT if sent else phrases.TEST_MORNING_SKIPPED)


@router.message(Command("test_monthly_summary"))
async def cmd_test_monthly_summary(message: Message, bot: Bot):
    if not _is_admin(message):
        return
    from datetime import timedelta

    from sqlalchemy import select

    from ...db.database import async_session_maker
    from ...db.models.models import Budget
    from ...services.monthly_report import (
        build_summary_data,
        format_summary_text,
        get_average_expenses,
        get_period_dates,
    )
    from ...utils.helpers import get_msk_now
    from ..keyboards import get_rollover_keyboard
    from ..rich_api import send_rich_message

    tg_id = message.from_user.id

    today = get_msk_now().date()
    async with async_session_maker() as session:
        result = await session.execute(
            select(Budget).where(Budget.telegram_id == tg_id).order_by(Budget.month.desc())
        )
        budgets = list(result.scalars().all())

    if not budgets:
        await message.answer(phrases.TEST_NO_BUDGET)
        return

    budget = None
    completed_budgets = []
    for b in budgets:
        _, pe = get_period_dates(b)
        if today == pe.date() + timedelta(days=1):
            budget = b
            break
        if pe.date() < today:
            completed_budgets.append((pe.date(), b))
    if not budget and completed_budgets:
        completed_budgets.sort(key=lambda x: x[0], reverse=True)
        budget = completed_budgets[0][1]
    if not budget:
        budget = budgets[0]

    await message.answer(phrases.TEST_MONTHLY_START)

    data = await build_summary_data(tg_id, budget)
    msg = format_summary_text(data)
    await send_rich_message(bot, tg_id, msg)

    avg = await get_average_expenses(tg_id)
    offer = phrases.ROLLOVER_OFFER.format(
        old_date=budget.period_start_day or 1,
        avg=int(avg) if avg > 0 else 0,
        old_income=int(budget.total_income),
    )
    await bot.send_message(tg_id, offer, reply_markup=get_rollover_keyboard(budget.id))
