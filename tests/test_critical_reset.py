from unittest.mock import AsyncMock, MagicMock, patch

from src.bot.handlers.menu import (
    CriticalReset,
    FreshStart,
    fresh_start_save_balance,
    fresh_start_save_black_day,
    fresh_start_save_mandatory,
    save_real_balance,
    trigger_critical_reset,
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
# trigger_critical_reset
# =============================================================================

class TestTriggerCriticalReset:
    async def test_sets_state_and_prompts(self):
        cb = _make_callback("trigger_critical_reset")
        state = _make_state()

        await trigger_critical_reset(cb, state)

        state.set_state.assert_awaited_with(CriticalReset.waiting_for_real_balance)
        cb.message.answer.assert_awaited()


# =============================================================================
# save_real_balance — 3 зоны
# =============================================================================

class TestSaveRealBalanceGreen:
    async def test_green_zone_limit_above_500(self):
        msg = _make_message("100000")
        state = _make_state()

        with (
            patch("src.bot.handlers.menu.reconcile_budget_with_reality",
                  AsyncMock(return_value=(1500.0, 20, 30000.0, 50000.0, 20000.0))),
            patch("src.bot.handlers.menu.apply_reconciliation",
                  AsyncMock()),
            patch("src.bot.handlers.menu.get_main_menu_keyboard",
                  AsyncMock()),
        ):
            await save_real_balance(msg, state)

        state.clear.assert_awaited()
        msg.answer.assert_awaited()


class TestSaveRealBalanceYellow:
    async def test_yellow_zone_limit_100_to_500(self):
        msg = _make_message("100000")
        state = _make_state()

        with (
            patch("src.bot.handlers.menu.reconcile_budget_with_reality",
                  AsyncMock(return_value=(300.0, 20, 6000.0, 50000.0, 44000.0))),
            patch("src.bot.handlers.menu.apply_reconciliation",
                  AsyncMock()),
        ):
            await save_real_balance(msg, state)

        state.clear.assert_awaited()
        msg.answer.assert_awaited()


class TestSaveRealBalanceRed:
    async def test_red_zone_limit_below_100_sets_fresh_start(self):
        msg = _make_message("50000")
        state = _make_state()

        with (
            patch("src.bot.handlers.menu.reconcile_budget_with_reality",
                  AsyncMock(return_value=(50.0, 20, 1000.0, 30000.0, 19000.0))),
            patch("src.bot.handlers.menu.apply_reconciliation"),
        ):
            await save_real_balance(msg, state)

        state.set_state.assert_awaited_with(FreshStart.waiting_for_mandatory)
        msg.answer.assert_awaited()


    async def test_red_zone_zero_limit(self):
        msg = _make_message("10000")
        state = _make_state()

        with (
            patch("src.bot.handlers.menu.reconcile_budget_with_reality",
                  AsyncMock(return_value=(0.0, 20, 0.0, 8000.0, 2000.0))),
            patch("src.bot.handlers.menu.apply_reconciliation"),
        ):
            await save_real_balance(msg, state)

        state.set_state.assert_awaited_with(FreshStart.waiting_for_mandatory)

    async def test_invalid_amount_returns_error(self):
        msg = _make_message("abc")
        state = _make_state()

        await save_real_balance(msg, state)

        msg.answer.assert_awaited()
        state.set_state.assert_not_called()
        state.clear.assert_not_called()

    async def test_no_budget_handled_gracefully(self):
        msg = _make_message("50000")
        state = _make_state()

        with (
            patch("src.bot.handlers.menu.reconcile_budget_with_reality",
                  AsyncMock(return_value=(0.0, 1, 0.0, 0.0, 0.0))),
            patch("src.bot.handlers.menu.apply_reconciliation"),
        ):
            await save_real_balance(msg, state)


# =============================================================================
# FreshStart FSM
# =============================================================================

class TestFreshStartSaveMandatory:
    async def test_valid_mandatory_sets_state(self):
        msg = _make_message("15000")
        state = _make_state()

        await fresh_start_save_mandatory(msg, state)

        state.update_data.assert_awaited_with(fresh_mandatory=15000.0)
        state.set_state.assert_awaited_with(FreshStart.waiting_for_black_day)

    async def test_zero_allowed(self):
        msg = _make_message("0")
        state = _make_state()

        await fresh_start_save_mandatory(msg, state)

        state.update_data.assert_awaited_with(fresh_mandatory=0.0)

    async def test_invalid_returns_error(self):
        msg = _make_message("abc")
        state = _make_state()

        await fresh_start_save_mandatory(msg, state)

        state.set_state.assert_not_called()


class TestFreshStartSaveBlackDay:
    async def test_valid_amount_sets_state(self):
        msg = _make_message("5000")
        state = _make_state()

        await fresh_start_save_black_day(msg, state)

        state.update_data.assert_awaited_with(fresh_black_day=5000.0)
        state.set_state.assert_awaited_with(FreshStart.waiting_for_balance)

    async def test_zero_allowed(self):
        msg = _make_message("0")
        state = _make_state()

        await fresh_start_save_black_day(msg, state)

        state.update_data.assert_awaited_with(fresh_black_day=0.0)

    async def test_invalid_returns_error(self):
        msg = _make_message("abc")
        state = _make_state()

        await fresh_start_save_black_day(msg, state)

        state.set_state.assert_not_called()


class TestFreshStartSaveBalance:
    async def test_valid_balance_completes_flow(self):
        msg = _make_message("60000")
        state = _make_state(fresh_mandatory=15000.0, fresh_black_day=5000.0)

        with (
            patch("src.bot.handlers.menu.get_budget_or_none",
                  AsyncMock(return_value=MagicMock(days_remaining=15))),
            patch("src.bot.handlers.menu.apply_reconciliation",
                  AsyncMock()),
            patch("src.bot.handlers.menu.get_main_menu_keyboard",
                  AsyncMock()),
        ):
            await fresh_start_save_balance(msg, state)

        state.clear.assert_awaited()
        msg.answer.assert_awaited()

    async def test_invalid_input_returns_error(self):
        msg = _make_message("abc")
        state = _make_state()

        await fresh_start_save_balance(msg, state)

        state.clear.assert_not_called()
        state.set_state.assert_not_called()

    async def test_no_budget_fallback_days(self):
        msg = _make_message("50000")
        state = _make_state(fresh_mandatory=10000.0, fresh_black_day=5000.0)

        with (
            patch("src.bot.handlers.menu.get_budget_or_none",
                  AsyncMock(return_value=None)),
            patch("src.bot.handlers.menu.apply_reconciliation",
                  AsyncMock()),
            patch("src.bot.handlers.menu.get_main_menu_keyboard",
                  AsyncMock()),
        ):
            await fresh_start_save_balance(msg, state)

        state.clear.assert_awaited()
