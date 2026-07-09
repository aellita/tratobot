from unittest.mock import AsyncMock, MagicMock, patch

from src.bot.handlers.menu import (
    EditBudget,
    change_budget,
    change_budget_add,
    change_budget_recalc,
    recalc_limit,
    save_recalc_balance,
)


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


class TestRecalcLimit:
    async def test_sets_state_and_prompts(self):
        cb = _make_callback("recalc_limit")
        state = _make_state()

        await recalc_limit(cb, state)

        state.set_state.assert_awaited_with(EditBudget.waiting_for_recalc_balance)
        cb.message.answer.assert_awaited()


class TestSaveRecalcBalance:
    async def test_valid_balance_applies_and_clears(self):
        msg = _make_message("100000")
        state = _make_state()

        with (
            patch(
                "src.bot.handlers.menu.reconcile_budget_with_reality",
                AsyncMock(return_value=(1500.0, 20, 30000.0, 50000.0, 20000.0)),
            ),
            patch("src.bot.handlers.menu.apply_reconciliation", AsyncMock()),
            patch("src.bot.handlers.menu.get_main_menu_keyboard", AsyncMock()),
        ):
            await save_recalc_balance(msg, state)

        state.clear.assert_awaited()
        msg.answer.assert_awaited()

    async def test_invalid_amount_returns_error(self):
        msg = _make_message("abc")
        state = _make_state()

        await save_recalc_balance(msg, state)

        msg.answer.assert_awaited()
        state.set_state.assert_not_called()
        state.clear.assert_not_called()

    async def test_zero_balance_allowed(self):
        msg = _make_message("0")
        state = _make_state()

        with (
            patch(
                "src.bot.handlers.menu.reconcile_budget_with_reality",
                AsyncMock(return_value=(0.0, 20, 0.0, 0.0, 0.0)),
            ),
            patch("src.bot.handlers.menu.apply_reconciliation", AsyncMock()),
            patch("src.bot.handlers.menu.get_main_menu_keyboard", AsyncMock()),
        ):
            await save_recalc_balance(msg, state)

        state.clear.assert_awaited()
        msg.answer.assert_awaited()

    async def test_no_budget_handled_gracefully(self):
        msg = _make_message("50000")
        state = _make_state()

        with (
            patch(
                "src.bot.handlers.menu.reconcile_budget_with_reality",
                AsyncMock(return_value=(0.0, 1, 0.0, 0.0, 0.0)),
            ),
            patch("src.bot.handlers.menu.apply_reconciliation"),
        ):
            await save_recalc_balance(msg, state)


class TestChangeBudget:
    async def test_shows_choice_keyboard(self):
        cb = _make_callback("change_budget")
        state = _make_state()

        with patch("src.bot.handlers.menu.get_change_budget_choice_keyboard"):
            await change_budget(cb, state)

        cb.message.edit_text.assert_awaited()

    async def test_add_income_sets_state(self):
        cb = _make_callback("change_budget_add")
        state = _make_state()

        with patch("src.bot.handlers.menu.get_cancel_keyboard"):
            await change_budget_add(cb, state)

        state.set_state.assert_awaited_with(EditBudget.waiting_for_add_income)
        cb.message.edit_text.assert_awaited()

    async def test_recalc_sets_state(self):
        cb = _make_callback("change_budget_recalc")
        state = _make_state()

        await change_budget_recalc(cb, state)

        state.set_state.assert_awaited_with(EditBudget.waiting_for_recalc_balance)
        cb.message.edit_text.assert_awaited()
