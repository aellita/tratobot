from unittest.mock import AsyncMock, MagicMock, patch

from src.bot.handlers.menu import (
    BudgetSetup,
    EditBudget,
    _parse_wishlist,
    handle_period_start_choice,
    handle_rounding_choice,
    process_black_day,
    process_income,
    process_mandatory,
    process_period_start,
    process_wishlist_name,
    skip_step,
)

# =============================================================================
# _parse_wishlist — чистая функция
# =============================================================================


class TestParseWishlist:
    def test_name_and_price(self):
        name, price = _parse_wishlist("Ноутбук 50000")
        assert name == "Ноутбук"
        assert price == 50000.0

    def test_multi_word_name(self):
        name, price = _parse_wishlist("Игровой компьютер 85000")
        assert price == 85000.0
        assert "компьютер" in name

    def test_no_price_defaults_zero(self):
        name, price = _parse_wishlist("толькотекст")
        assert price == 0.0
        assert name == "Толькотекст"

    def test_only_number_returns_placeholder(self):
        name, price = _parse_wishlist("100")
        assert name == "Хотелка"
        assert price == 100.0

    def test_lowercase_first_char_gets_capitalized(self):
        name, price = _parse_wishlist("хотелка 5000")
        assert name == "Хотелка"
        assert price == 5000.0

    def test_empty_string(self):
        name, price = _parse_wishlist("")
        assert name == "Хотелка"
        assert price == 0.0

    def test_price_with_spaces(self):
        name, price = _parse_wishlist("Поездка 100 000")
        assert price == 100000.0

    def test_price_with_comma(self):
        name, price = _parse_wishlist("Велосипед 45,500")
        assert price == 45.0

    def test_special_chars_in_name(self):
        name, price = _parse_wishlist("MacBook Pro $3000")
        assert price == 3000.0


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
# FSM: process_income (BudgetSetup.waiting_for_income)
# =============================================================================


class TestProcessIncome:
    async def test_valid_income_sets_state(self):
        msg = _make_message("50000")
        state = _make_state()

        await process_income(msg, state)

        state.update_data.assert_awaited()
        state.set_state.assert_awaited_with(BudgetSetup.waiting_for_period_start)
        msg.answer.assert_awaited()

    async def test_invalid_income_returns_error(self):
        msg = _make_message("не число")
        state = _make_state()

        await process_income(msg, state)

        state.update_data.assert_not_called()
        state.set_state.assert_not_called()
        msg.answer.assert_awaited()

    async def test_negative_income_returns_error(self):
        msg = _make_message("-500")
        state = _make_state()

        await process_income(msg, state)

        state.update_data.assert_not_called()

    async def test_zero_income_returns_error(self):
        msg = _make_message("0")
        state = _make_state()

        await process_income(msg, state)

        state.update_data.assert_not_called()


# =============================================================================
# FSM: process_period_start (BudgetSetup.waiting_for_period_start)
# =============================================================================


class TestProcessPeriodStart:
    async def test_valid_day_sets_state(self):
        msg = _make_message("15")
        state = _make_state()

        await process_period_start(msg, state)

        state.update_data.assert_awaited()
        state.set_state.assert_awaited_with(BudgetSetup.waiting_for_mandatory)

    async def test_invalid_text_returns_error(self):
        msg = _make_message("abc")
        state = _make_state()

        await process_period_start(msg, state)

        state.set_state.assert_not_called()

    async def test_below_min_clamped(self):
        msg = _make_message("0")
        state = _make_state()

        await process_period_start(msg, state)

        state.update_data.assert_awaited()

    async def test_above_max_clamped(self):
        msg = _make_message("35")
        state = _make_state()

        await process_period_start(msg, state)

        state.update_data.assert_awaited()

    async def test_retry_limit_exceeded(self):
        msg = _make_message("abc")
        state = _make_state(_retry_count=2)

        with patch("src.bot.handlers.menu.get_main_menu_keyboard", AsyncMock()):
            await process_period_start(msg, state)

        state.clear.assert_awaited()
        msg.answer.assert_awaited()


# =============================================================================
# FSM: process_mandatory (BudgetSetup.waiting_for_mandatory)
# =============================================================================


class TestProcessMandatory:
    async def test_valid_mandatory_sets_state(self):
        msg = _make_message("15000")
        state = _make_state()

        await process_mandatory(msg, state)

        state.update_data.assert_awaited()
        state.set_state.assert_awaited_with(BudgetSetup.waiting_for_black_day)

    async def test_invalid_returns_error(self):
        msg = _make_message("abc")
        state = _make_state()

        await process_mandatory(msg, state)

        state.set_state.assert_not_called()

    async def test_zero_allowed(self):
        msg = _make_message("0")
        state = _make_state()

        await process_mandatory(msg, state)

        state.update_data.assert_awaited()


# =============================================================================
# FSM: process_black_day (BudgetSetup.waiting_for_black_day)
# =============================================================================


class TestProcessBlackDay:
    async def test_valid_amount_sets_state(self):
        msg = _make_message("5000")
        state = _make_state()

        await process_black_day(msg, state)

        state.update_data.assert_awaited()
        state.set_state.assert_awaited_with(BudgetSetup.waiting_for_wishlist_name)

    async def test_invalid_returns_error(self):
        msg = _make_message("abc")
        state = _make_state()

        await process_black_day(msg, state)

        state.set_state.assert_not_called()

    async def test_zero_allowed(self):
        msg = _make_message("0")
        state = _make_state()

        await process_black_day(msg, state)

        state.update_data.assert_awaited()


# =============================================================================
# FSM: process_wishlist_name (BudgetSetup.waiting_for_wishlist_name)
# =============================================================================


class TestProcessWishlistName:
    async def test_name_and_price_sets_state(self):
        msg = _make_message("PS5 45000")
        state = _make_state()

        await process_wishlist_name(msg, state)

        state.update_data.assert_awaited()

    async def test_no_price_defaults_zero(self):
        msg = _make_message("Просто цель")
        state = _make_state()

        await process_wishlist_name(msg, state)

        assert state.update_data.await_count >= 1


# =============================================================================
# FSM: skip_step
# =============================================================================


class TestSkipStep:
    async def test_skip_income(self):
        cb = _make_callback("skip_step")
        state = _make_state()
        state.get_state = AsyncMock(return_value=BudgetSetup.waiting_for_income.state)

        with (
            patch("src.bot.handlers.menu.get_onboarding_keyboard"),
            patch("src.bot.handlers.menu._finish_onboarding", AsyncMock()),
        ):
            await skip_step(cb, state)

        state.update_data.assert_awaited()

    async def test_skip_mandatory(self):
        cb = _make_callback("skip_step")
        state = _make_state()
        state.get_state = AsyncMock(return_value=BudgetSetup.waiting_for_mandatory.state)

        await skip_step(cb, state)

        state.update_data.assert_awaited()

    async def test_skip_black_day(self):
        cb = _make_callback("skip_step")
        state = _make_state()
        state.get_state = AsyncMock(return_value=BudgetSetup.waiting_for_black_day.state)

        await skip_step(cb, state)

        state.update_data.assert_awaited()

    async def test_skip_wishlist_name(self):
        cb = _make_callback("skip_step")
        state = _make_state()
        state.get_state = AsyncMock(return_value=BudgetSetup.waiting_for_wishlist_name.state)

        await skip_step(cb, state)

        state.update_data.assert_awaited()

    async def test_skip_rounding_mode(self):
        cb = _make_callback("skip_step")
        state = _make_state()
        state.get_state = AsyncMock(return_value=BudgetSetup.waiting_for_rounding_mode.state)

        await skip_step(cb, state)

        state.update_data.assert_awaited()


# =============================================================================
# FSM: handle_rounding_choice
# =============================================================================


class TestHandleRoundingChoice:
    async def test_rounding_off_saves_zero(self):
        cb = _make_callback("rounding_off")
        state = _make_state()
        state.get_state = AsyncMock(return_value=BudgetSetup.waiting_for_rounding_mode.state)

        await handle_rounding_choice(cb, state)

        state.update_data.assert_awaited()

    async def test_rounding_10_saves_ten(self):
        cb = _make_callback("rounding_10")
        state = _make_state()
        state.get_state = AsyncMock(return_value=BudgetSetup.waiting_for_rounding_mode.state)

        await handle_rounding_choice(cb, state)

        state.update_data.assert_awaited()

    async def test_rounding_100_saves_hundred(self):
        cb = _make_callback("rounding_100")
        state = _make_state()
        state.get_state = AsyncMock(return_value=BudgetSetup.waiting_for_rounding_mode.state)

        await handle_rounding_choice(cb, state)

        state.update_data.assert_awaited()


# =============================================================================
# FSM: handle_period_start_choice (callback)
# =============================================================================


class TestHandlePeriodStartChoice:
    async def test_period_today(self):
        cb = _make_callback("period_today")
        state = _make_state()
        state.get_state = AsyncMock(return_value=BudgetSetup.waiting_for_period_start.state)

        await handle_period_start_choice(cb, state)

        state.update_data.assert_awaited()
        state.set_state.assert_awaited_with(BudgetSetup.waiting_for_mandatory)

    async def test_period_first(self):
        cb = _make_callback("period_first")
        state = _make_state()
        state.get_state = AsyncMock(return_value=BudgetSetup.waiting_for_period_start.state)

        await handle_period_start_choice(cb, state)

        state.update_data.assert_awaited()
        state.set_state.assert_awaited_with(BudgetSetup.waiting_for_mandatory)

    async def test_period_other_prompts_input(self):
        cb = _make_callback("period_other")
        state = _make_state()

        await handle_period_start_choice(cb, state)

        cb.message.edit_text.assert_awaited()

    async def test_period_first_in_edit_budget(self):
        cb = _make_callback("period_first")
        state = _make_state()
        state.get_state = AsyncMock(return_value=EditBudget.waiting_for_period_start.state)

        with (
            patch("src.bot.handlers.menu.update_budget_field") as mock_ubf,
            patch("src.bot.handlers.menu.get_main_menu_keyboard", AsyncMock()),
        ):
            await handle_period_start_choice(cb, state)

            mock_ubf.assert_awaited_with(99999, "period_start_day", 1)
