from unittest.mock import AsyncMock, MagicMock, patch

from src.bot.handlers.history import (
    save_edit_expense,
    start_edit_expense,
)

# =============================================================================
# Вспомогательные моки
# =============================================================================

def _make_message(text: str, user_id: int = 99999, first_name: str = "Test") -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.from_user.id = user_id
    msg.from_user.first_name = first_name
    msg.from_user.username = "testuser"
    msg.chat.id = user_id
    msg.message_id = 1
    msg.bot = MagicMock()
    msg.bot.edit_message_reply_markup = AsyncMock()
    msg.answer = AsyncMock(return_value=msg)
    msg.delete = AsyncMock()
    return msg


def _make_callback(data: str, user_id: int = 99999, first_name: str = "Test") -> MagicMock:
    cb = MagicMock()
    cb.data = data
    cb.from_user.id = user_id
    cb.from_user.first_name = first_name
    cb.from_user.username = "testuser"
    cb.message.chat.id = user_id
    cb.message.message_id = 1
    cb.message.edit_text = AsyncMock()
    cb.message.delete = AsyncMock()
    cb.message.bot = MagicMock()
    cb.message.bot.edit_message_reply_markup = AsyncMock()
    cb.message.answer = AsyncMock()
    cb.answer = AsyncMock()
    return cb


def _make_state(**initial_data) -> AsyncMock:
    state = AsyncMock()
    state.get_data = AsyncMock(return_value=initial_data)
    return state


# =============================================================================
# save_edit_expense (EditExpense.waiting_for_amount)
# =============================================================================

class TestSaveEditExpense:
    async def test_valid_amount_updates_expense(self):
        msg = _make_message("1500")
        state = _make_state(edit_expense_id=42)

        with (
            patch("src.bot.handlers.history.update_expense_amount",
                  AsyncMock(return_value=MagicMock(amount=1500.0, description="кофе"))),
            patch("src.bot.handlers.history.get_main_menu_keyboard", AsyncMock()),
        ):
            await save_edit_expense(msg, state)

        state.clear.assert_awaited()
        msg.answer.assert_awaited()

    async def test_invalid_amount_returns_error(self):
        msg = _make_message("abc")
        state = _make_state(edit_expense_id=42)

        await save_edit_expense(msg, state)

        msg.answer.assert_awaited()
        state.clear.assert_not_called()

    async def test_retry_limit_exceeded(self):
        msg = _make_message("abc")
        state = _make_state(edit_expense_id=42, _retry_count=2)

        with patch("src.bot.handlers.history.get_main_menu_keyboard", AsyncMock()):
            await save_edit_expense(msg, state)

        state.clear.assert_awaited()
        msg.answer.assert_awaited()

    async def test_expense_not_found(self):
        msg = _make_message("1500")
        state = _make_state(edit_expense_id=42)

        with (
            patch("src.bot.handlers.history.update_expense_amount",
                  AsyncMock(return_value=None)),
        ):
            await save_edit_expense(msg, state)

        state.clear.assert_awaited()
        msg.answer.assert_awaited()

    async def test_no_expense_id_clears_state(self):
        msg = _make_message("1500")
        state = _make_state()

        await save_edit_expense(msg, state)

        state.clear.assert_awaited()

    async def test_negative_amount_returns_error(self):
        msg = _make_message("-500")
        state = _make_state(edit_expense_id=42)

        await save_edit_expense(msg, state)

        msg.answer.assert_awaited()
        state.clear.assert_not_called()

    async def test_valid_amount_with_special_chars(self):
        msg = _make_message("1500,50")
        state = _make_state(edit_expense_id=42)

        with (
            patch("src.bot.handlers.history.update_expense_amount",
                  AsyncMock(return_value=MagicMock(amount=1500.5, description="трата"))),
            patch("src.bot.handlers.history.get_main_menu_keyboard", AsyncMock()),
        ):
            await save_edit_expense(msg, state)

        state.clear.assert_awaited()


# =============================================================================
# start_edit_expense (callback)
# =============================================================================

class TestStartEditExpense:
    async def test_valid_expense_id_sets_state(self):
        cb = _make_callback("exp_edit:42")
        state = _make_state()

        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=MagicMock(id=42, amount=500.0, description="кофе")),
        ))
        mock_maker = MagicMock(return_value=mock_session)
        cb.message.edit_text.return_value = None

        with patch("src.bot.handlers.history.async_session_maker", mock_maker):
            await start_edit_expense(cb, state)

        state.update_data.assert_awaited_with(edit_expense_id=42)

    async def test_invalid_callback_data(self):
        cb = _make_callback("exp_edit:abc")
        state = _make_state()

        with patch("src.bot.handlers.history.get_main_menu_keyboard", AsyncMock()):
            await start_edit_expense(cb, state)

        cb.message.edit_text.assert_awaited()
        state.set_state.assert_not_called()

    async def test_expense_not_found(self):
        cb = _make_callback("exp_edit:99999")
        state = _make_state()

        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None),
        ))
        mock_maker = MagicMock(return_value=mock_session)

        with (
            patch("src.bot.handlers.history.async_session_maker", mock_maker),
            patch("src.bot.handlers.history.get_main_menu_keyboard", AsyncMock()),
        ):
            await start_edit_expense(cb, state)

        cb.message.edit_text.assert_awaited()
        state.set_state.assert_not_called()
