from src.services.evening_report import get_evening_message
from src.utils import phrases


class TestEveningZeroLimit:
    def test_zero_limit_and_zero_spent_is_honest(self):
        text = get_evening_message(limit=0, spent=0, available_cash=0, days_left=5)
        assert text == phrases.EVENING_ZERO_NO_MONEY
        assert "нет бюджета" not in text.lower()

    def test_negative_limit_and_zero_spent_is_honest(self):
        text = get_evening_message(limit=-100, spent=0, available_cash=0, days_left=5)
        assert text == phrases.EVENING_ZERO_NO_MONEY

    def test_positive_limit_zero_spent_uses_regular_phrases(self):
        text = get_evening_message(limit=5000, spent=0, available_cash=20000, days_left=5)
        assert text != phrases.EVENING_ZERO_NO_MONEY
        assert text in {
            phrases.EVENING_ZERO_1.format(limit=5000),
            phrases.EVENING_ZERO_2,
            phrases.EVENING_ZERO_3,
        }

    def test_zero_limit_with_spending_does_not_crash(self):
        text = get_evening_message(limit=0, spent=1000, available_cash=0, days_left=5)
        assert isinstance(text, str)
        assert text
