from datetime import datetime

from src.db.models.models import Budget, Expense, User
from src.utils import phrases


def _freeze(monkeypatch, dt):
    monkeypatch.setattr("src.db.models.models._msk_now", lambda: dt)
    monkeypatch.setattr("src.bot.handlers.menu.get_msk_now", lambda: dt)
    monkeypatch.setattr("src.services.budget_service.get_msk_now", lambda: dt)
    monkeypatch.setattr("src.services.expense_service.get_msk_now", lambda: dt)


class TestSettingsMoney:
    @staticmethod
    async def _settings(db_session, *, free_money: float, total_income: float = 0, expenses=()):
        db_session.add(User(telegram_id=1001))
        db_session.add(
            Budget(
                telegram_id=1001,
                month="2026-09",
                total_income=total_income,
                free_money=free_money,
                spent_at_recalc=0,
                period_start_day=1,
            )
        )
        for amount, date in expenses:
            db_session.add(
                Expense(
                    telegram_id=1001,
                    amount=amount,
                    description="траты",
                    date=date,
                )
            )
        await db_session.commit()

        from src.bot.handlers.menu import _render_settings

        return (await _render_settings(1001))[0]

    async def test_shows_current_remainder_not_snapshot(self, db_session, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 9, 14))
        # На карте при пересчёте было 50 000, после этого потрачено 20 000.
        text = await self._settings(
            db_session,
            free_money=50000,
            expenses=[(20000, datetime(2026, 9, 5))],
        )

        assert phrases.SETTINGS_MONEY_REMAINING.format(amount="30,000") in text
        assert "50,000" not in text

    async def test_remainder_matches_status_formula_after_recalc(self, db_session, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 9, 14))
        # 50 000 на карте при пересчёте, 10 000 из трат уже были учтены.
        db_session.add(User(telegram_id=1001))
        db_session.add(
            Budget(
                telegram_id=1001,
                month="2026-09",
                total_income=0,
                free_money=50000,
                spent_at_recalc=10000,
                period_start_day=1,
            )
        )
        db_session.add(
            Expense(
                telegram_id=1001,
                amount=20000,
                description="траты",
                date=datetime(2026, 9, 5),
            )
        )
        await db_session.commit()

        from src.bot.handlers.menu import _render_settings

        text, _ = await _render_settings(1001)
        assert phrases.SETTINGS_MONEY_REMAINING.format(amount="40,000") in text

    async def test_shows_income_when_no_snapshot(self, db_session, monkeypatch):
        _freeze(monkeypatch, datetime(2026, 9, 14))
        text = await self._settings(db_session, free_money=0, total_income=100000)

        assert phrases.SETTINGS_MONEY_INCOME.format(amount="100,000") in text
        assert "Остаток:" not in text
