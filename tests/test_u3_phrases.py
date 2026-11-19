import pytest

from src.utils import phrases


class TestEndOkVariants:
    def test_three_distinct_texts_with_same_placeholders(self):
        variants = [phrases.END_OK, phrases.END_OK_1, phrases.END_OK_2]
        texts = {v.format(days=2, days_word="дня", money=2918.0) for v in variants}

        assert len(texts) == 3
        assert all("2 дня" in text for text in texts)
        assert sum("2,918" in text for text in texts) == 2

    def test_old_zone_names_removed(self):
        assert not hasattr(phrases, "ZONE_END_OK_1")
        assert not hasattr(phrases, "ZONE_END_OK_2")


class TestFooterVariants:
    @staticmethod
    def _footer(monkeypatch, *, plan_today: float):
        from src.bot.handlers.menu import _pick_status_footer

        # Берём средний вариант из списка, чтобы проверить, что он не мёртвый.
        monkeypatch.setattr(
            "src.bot.handlers.menu.random.choice", lambda options: options[len(options) // 2]
        )
        return _pick_status_footer(
            end_of_period=False,
            money_for_life=20000,
            overrun_today=0,
            free_today=1000,
            plan_today=plan_today,
            plan_tomorrow=500,
            days_left=10,
            base_daily_limit=10000,
        )

    def test_yellow_none_2_is_in_rotation(self, monkeypatch):
        footer, has_number = self._footer(monkeypatch, plan_today=3000)

        assert footer == phrases.STATUS_FOOTER_YELLOW_NONE_2.format(limit="500")
        assert has_number is True

    def test_red_none_2_is_in_rotation(self, monkeypatch):
        footer, has_number = self._footer(monkeypatch, plan_today=2000)

        assert footer == phrases.STATUS_FOOTER_RED_NONE_2.format(limit="500")
        assert has_number is True


class TestDeletedPhrases:
    @pytest.mark.parametrize(
        "name",
        [
            "BTN_ECONOMIZE",
            "BTN_STATUS",
            "BTN_ROUNDING",
            "NO_BUDGET_SHORT",
            "NO_BUDGET_MONTH",
            "STATUS_REMAINING_OK",
            "STATUS_REMAINING_STOP",
            "STATUS_SPENT_TODAY",
            "STATUS_BIG_SPEND",
            "STATUS_PERIOD_NEGATIVE",
            "STATUS_PERIOD_POSITIVE",
            "STATUS_PERIOD_ZERO",
            "CANCEL_RECALC",
            "TAKEN_FROM_SAVINGS",
            "BUDGET_COMPLETE",
            "INCOME_SAVED_PERIOD",
            "PERIOD_SET_PERIOD",
            "UNRECOGNIZED_TEXT",
            "ROUND_UP",
            "CATEGORY_MANAGEMENT_TITLE",
            "CATEGORY_LIST_ACTIVE_HEADER",
            "CATEGORY_LIST_ARCHIVED_HEADER",
            "STATUS_PLAN_TODAY",
        ],
    )
    def test_removed(self, name):
        assert not hasattr(phrases, name)
