from datetime import datetime
from types import SimpleNamespace

from src.db.models.models import Budget, Expense, User
from src.services.monthly_report import (
    build_summary_data,
    compute_avg_day,
    compute_saved_state,
    format_summary_text,
)
from src.utils import phrases
from src.utils.helpers import get_msk_now, period_dates, period_total_days


def _period(month: str, start_day: int) -> tuple[datetime, int]:
    period_start, _ = period_dates(month, start_day)
    return period_start, period_total_days(month, start_day)


class TestAvgDayClosedPeriod:
    def test_31_day_period(self):
        start, days = _period("2026-08", 20)
        avg = compute_avg_day(80000.0, start, days, False, datetime(2026, 9, 20))
        assert days == 31
        assert avg == 80000.0 / 31
        assert f"{avg:,.0f}" == "2,581"

    def test_28_day_february(self):
        start, days = _period("2026-02", 1)
        avg = compute_avg_day(80000.0, start, days, False, datetime(2026, 3, 1))
        assert days == 28
        assert avg == 80000.0 / 28
        assert f"{avg:,.0f}" == "2,857"

    def test_30_day_period(self):
        start, days = _period("2026-09", 1)
        avg = compute_avg_day(80000.0, start, days, False, datetime(2026, 10, 1))
        assert days == 30
        assert f"{avg:,.0f}" == "2,667"

    def test_closed_period_does_not_depend_on_today(self):
        start, days = _period("2026-08", 20)
        first = compute_avg_day(80000.0, start, days, False, datetime(2026, 9, 20))
        second = compute_avg_day(80000.0, start, days, False, datetime(2027, 1, 1))
        assert first == second


class TestAvgDayActivePeriod:
    def test_fifth_day_of_period(self):
        start, days = _period("2026-09", 1)
        avg = compute_avg_day(10000.0, start, days, True, datetime(2026, 9, 5))
        assert avg == 10000.0 / 5

    def test_offset_start_counts_from_period_start(self):
        start, days = _period("2026-08", 20)
        avg = compute_avg_day(17000.0, start, days, True, datetime(2026, 9, 5))
        assert days == 31
        assert avg == 17000.0 / 17

    def test_first_day_uses_one_day(self):
        start, days = _period("2026-09", 1)
        avg = compute_avg_day(1000.0, start, days, True, datetime(2026, 9, 1))
        assert avg == 1000.0

    def test_last_day_uses_full_period(self):
        start, days = _period("2026-09", 1)
        avg = compute_avg_day(30000.0, start, days, True, datetime(2026, 9, 30))
        assert avg == 30000.0 / 30

    def test_elapsed_days_are_capped_by_period_length(self):
        start, days = _period("2026-09", 1)
        avg = compute_avg_day(30000.0, start, days, True, datetime(2026, 10, 5))
        assert avg == 30000.0 / 30

    def test_zero_spent(self):
        start, days = _period("2026-09", 1)
        assert compute_avg_day(0.0, start, days, True, datetime(2026, 9, 5)) == 0.0


def _summary_data(total_spent: float = 80000.0) -> dict:
    return {
        "budget": SimpleNamespace(
            total_income=100000.0,
            daily_limit=3000.0,
            mandatory_payments=10000.0,
            black_day_fund=0.0,
            period_start_day=1,
        ),
        "active": False,
        "period_start": datetime(2026, 9, 1),
        "period_end": datetime(2026, 9, 30, 23, 59, 59),
        "breakdown": [],
        "total_spent": total_spent,
        "avg_day": 0.0,
        "income": 100000.0,
        "added_income": 0.0,
        "available": 90000.0,
        "saved": compute_saved_state(90000.0, total_spent)[0],
        "saved_tier": compute_saved_state(90000.0, total_spent)[1],
        "top_cat_name": "—",
        "totem_name": "Чебурашка",
        "totem_phrase": "—",
        "totem_emoji": "🍊",
        "period_label": "1 сен – 30 сен 2026",
    }


class TestM4SavedState:
    """M4: тон и сумма «Сэкономлено/Перерасход» считаются от доступной базы."""

    def test_green_up_to_70_percent(self):
        assert compute_saved_state(100000.0, 70000.0) == (30000, "green")

    def test_blue_above_70_percent(self):
        assert compute_saved_state(100000.0, 70001.0) == (29999, "blue")

    def test_blue_up_to_90_percent(self):
        assert compute_saved_state(100000.0, 90000.0) == (10000, "blue")

    def test_yellow_above_90_percent(self):
        assert compute_saved_state(100000.0, 90001.0) == (9999, "yellow")

    def test_exact_available_is_zero_not_yellow(self):
        assert compute_saved_state(100000.0, 100000.0) == (0, "zero")

    def test_rounding_below_half_ruble_is_zero(self):
        assert compute_saved_state(50000.0, 49999.6) == (0, "zero")

    def test_rounding_half_ruble_is_at_least_one(self):
        assert compute_saved_state(50000.0, 49999.4) == (1, "yellow")

    def test_rounding_up_49999_60(self):
        assert compute_saved_state(50000.0, 0.4) == (50000, "green")

    def test_rounding_down_50000_40(self):
        assert compute_saved_state(50000.4, 0.0) == (50000, "green")

    def test_overrun(self):
        assert compute_saved_state(100000.0, 120000.0) == (-20000, "overrun")

    def test_no_limit_when_available_is_zero(self):
        assert compute_saved_state(0.0, 0.0) == (0, "no_limit")

    def test_no_limit_when_available_is_negative(self):
        assert compute_saved_state(-5000.0, 0.0) == (0, "no_limit")

    def test_closed_green_period_phrase(self):
        data = _summary_data(total_spent=50000.0)
        text = format_summary_text(data)
        assert phrases.MONTHLY_SAVED_GREEN.format(amount="40,000") in text

    def test_closed_blue_period_phrase(self):
        data = _summary_data(total_spent=80000.0)
        text = format_summary_text(data)
        assert phrases.MONTHLY_SAVED_BLUE.format(amount="10,000") in text

    def test_closed_yellow_period_phrase(self):
        data = _summary_data(total_spent=89000.0)
        text = format_summary_text(data)
        assert phrases.MONTHLY_SAVED_YELLOW.format(amount="1,000") in text

    def test_closed_zero_period_phrase(self):
        data = _summary_data(total_spent=90000.0)
        text = format_summary_text(data)
        assert phrases.MONTHLY_SAVED_ZERO in text

    def test_closed_overrun_phrase(self):
        data = _summary_data(total_spent=100000.0)
        text = format_summary_text(data)
        assert phrases.MONTHLY_OVERRUN.format(amount="10,000") in text

    def test_no_limit_phrase_without_fund(self):
        data = _summary_data(total_spent=10000.0)
        data.update({"available": 0.0, "saved": 0, "saved_tier": "no_limit"})
        text = format_summary_text(data)
        assert phrases.MONTHLY_NO_LIMIT in text
        assert phrases.MONTHLY_NO_LIMIT_FUND not in text

    def test_no_limit_phrase_with_fund(self):
        data = _summary_data(total_spent=10000.0)
        data["budget"].black_day_fund = 5000.0
        data.update({"available": 0.0, "saved": 0, "saved_tier": "no_limit"})
        text = format_summary_text(data)
        assert phrases.MONTHLY_NO_LIMIT_FUND in text

    def test_active_period_has_no_saved_line(self):
        data = _summary_data(total_spent=50000.0)
        data["active"] = True
        text = format_summary_text(data)
        assert "Сэкономлено" not in text
        assert "Перерасход" not in text
        assert phrases.MONTHLY_NO_LIMIT not in text

    def test_income_line_always_present(self):
        text = format_summary_text(_summary_data(total_spent=50000.0))
        assert phrases.MONTHLY_INCOME_LABEL.format(amount="100,000") in text

    def test_added_income_line_only_when_positive(self):
        data = _summary_data(total_spent=50000.0)
        data["added_income"] = 15000.0
        text = format_summary_text(data)
        assert phrases.MONTHLY_ADDED_INCOME.format(amount="15,000") in text

        data["added_income"] = 0.0
        text = format_summary_text(data)
        assert "Из них добавлено" not in text

    def test_no_zone_tag_anymore(self):
        text = format_summary_text(_summary_data(total_spent=50000.0))
        assert "Зона:" not in text

    def test_details_show_fund_when_positive(self):
        data = _summary_data(total_spent=50000.0)
        data["budget"].black_day_fund = 7000.0
        text = format_summary_text(data)
        assert "• Кубышка: <code>7,000 ₽</code>" in text


class TestDetailsSuffix:
    def test_last_code_tag_stays_closed(self):
        text = format_summary_text(_summary_data())
        assert "</code>\n</details>" in text
        assert "</code\n" not in text

    def test_details_end_with_mandatory_line(self):
        text = format_summary_text(_summary_data())
        assert text.endswith("Обязательные платежи: <code>10,000 ₽</code>\n</details>")


class TestM3NoCategorySorting:
    """M3: 'Без категории' participates in sort, not appended at the end."""

    def test_closed_period_no_category_top_totem_variant_a(self):
        """Closed period: top is 'Без категории' → MONTHLY_TOTEM_NO_CATEGORY phrase."""
        data = _summary_data(total_spent=50000.0)
        data.update(
            {
                "active": False,
                "breakdown": [(phrases.MONTHLY_NO_CATEGORY, 5, 50000.0)],
                "top_cat_name": phrases.MONTHLY_NO_CATEGORY,
                "totem_name": "Чебурашка",
                "totem_phrase": phrases.MONTHLY_TOTEM_DEFAULT.format(
                    category=phrases.MONTHLY_NO_CATEGORY
                ),
                "totem_emoji": "🍊",
            }
        )
        text = format_summary_text(data)
        assert "Твой тотем — Чебурашка" in text
        assert "Больше всего бюджета ушло в «Без категории»" in text
        assert "пока не раскидаешь эти траты" in text
        assert "мне не понять, что ты за зверь" in text

    def test_active_period_no_category_top_egg_variant_a(self):
        """Active period: top is 'Без категории' → MONTHLY_EGG_TOTEM_NO_CATEGORY phrase."""
        data = _summary_data(total_spent=50000.0)
        data.update(
            {
                "active": True,
                "breakdown": [(phrases.MONTHLY_NO_CATEGORY, 5, 50000.0)],
                "top_cat_name": phrases.MONTHLY_NO_CATEGORY,
                "totem_name": "Чебурашка",
                "totem_phrase": phrases.MONTHLY_TOTEM_DEFAULT.format(
                    category=phrases.MONTHLY_NO_CATEGORY
                ),
                "totem_emoji": "🍊",
            }
        )
        text = format_summary_text(data)
        assert "Твой тотем за сентября ещё зреет" in text
        assert "Пока там в топе «Без категории»" in text
        assert "Разбери эти траты, бро — и тотем вылупится точным" in text
        assert "лидируешь в категории" not in text  # old template not used

    def test_zero_expenses_shows_empty(self):
        """Zero expenses → MONTHLY_EMPTY message, no totem line."""
        data = _summary_data(total_spent=0.0)
        data.update(
            {
                "breakdown": [],
                "top_cat_name": "—",
            }
        )
        text = format_summary_text(data)
        assert "За этот период пока нет трат" in text
        assert "Начни записывать" in text


class TestBuildSummaryDataM4:
    """M4: интеграционная проверка базы, тона и добавленного дохода."""

    async def _seed(
        self,
        db_session,
        *,
        total_income: float = 100000.0,
        mandatory_payments: float = 10000.0,
        black_day_fund: float = 0.0,
        added_income: float = 0.0,
        expenses: list[float] | None = None,
    ) -> Budget:
        db_session.add(User(telegram_id=1001))
        budget = Budget(
            telegram_id=1001,
            month=get_msk_now().strftime("%Y-%m"),
            total_income=total_income,
            added_income=added_income,
            mandatory_payments=mandatory_payments,
            black_day_fund=black_day_fund,
            period_start_day=1,
        )
        db_session.add(budget)
        for i, amount in enumerate(expenses or []):
            db_session.add(
                Expense(
                    telegram_id=1001,
                    amount=amount,
                    description=f"e{i}",
                    date=get_msk_now(),
                )
            )
        await db_session.commit()
        return budget

    async def test_available_subtracts_mandatory_and_fund(self, db_session):
        budget = await self._seed(db_session, black_day_fund=5000.0)

        data = await build_summary_data(1001, budget)

        assert data["available"] == 85000.0
        assert data["income"] == 100000.0
        assert data["saved"] == 85000
        assert data["saved_tier"] == "green"

    async def test_saved_counts_from_available_not_income(self, db_session):
        budget = await self._seed(db_session, expenses=[80000.0])

        data = await build_summary_data(1001, budget)

        assert data["total_spent"] == 80000.0
        assert data["saved"] == 10000
        assert data["saved_tier"] == "blue"

    async def test_no_limit_when_mandatory_eats_income(self, db_session):
        budget = await self._seed(db_session, mandatory_payments=100000.0)

        data = await build_summary_data(1001, budget)

        assert data["available"] == 0.0
        assert data["saved"] == 0
        assert data["saved_tier"] == "no_limit"

    async def test_added_income_reaches_data_and_text(self, db_session):
        budget = await self._seed(db_session, added_income=15000.0)

        data = await build_summary_data(1001, budget)

        assert data["added_income"] == 15000.0
        text = format_summary_text(data)
        assert phrases.MONTHLY_ADDED_INCOME.format(amount="15,000") in text
