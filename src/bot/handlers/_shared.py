from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ...utils import phrases
from ...utils.helpers import check_retry
from ..keyboards import get_cancel_keyboard, get_main_menu_keyboard


async def handle_invalid_input(
    message: Message, state: FSMContext, error_text: str,
) -> None:
    """Increment retry; if 3rd failure clear state + timeout message."""
    data = await state.get_data()
    exhausted, next_retry = check_retry(data.get("_retry_count", 0))
    await state.update_data(_retry_count=next_retry)
    if exhausted:
        await state.clear()
        await message.answer(
            phrases.ERR_TOO_MANY_RETRIES,
            reply_markup=await get_main_menu_keyboard(message.from_user.id),
        )
        return
    await message.answer(error_text, reply_markup=get_cancel_keyboard())
