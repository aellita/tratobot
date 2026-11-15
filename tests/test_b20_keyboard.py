from src.bot.keyboards import get_change_budget_choice_keyboard
from src.utils import phrases


def test_each_budget_choice_button_has_its_own_row():
    rows = get_change_budget_choice_keyboard().inline_keyboard

    assert len(rows) == 3
    assert [button.text for button in rows[0]] == [phrases.BTN_CHANGE_BUDGET_ADD]
    assert [button.text for button in rows[1]] == [phrases.BTN_CHANGE_BUDGET_RECALC]
    assert [button.text for button in rows[2]] == [phrases.BTN_BACK]
