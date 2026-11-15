import inspect

from src.bot.keyboards import get_monthly_nav_keyboard
from src.db.models.models import Category, Expense, User
from src.services.expense_service import get_today_expenses_grouped
from src.utils import phrases
from src.utils.helpers import get_msk_now


class TestCategoryFormat:
    async def test_category_has_colon(self, db_session):
        db_session.add(User(telegram_id=1001))
        cat = Category(telegram_id=1001, name="🐱 Киси Кошке", keywords="[]")
        db_session.add(cat)
        await db_session.flush()
        db_session.add(
            Expense(
                telegram_id=1001,
                amount=1644.0,
                description="Суролан",
                category_id=cat.id,
                date=get_msk_now(),
            )
        )
        await db_session.commit()

        lines = await get_today_expenses_grouped(1001)

        assert lines == ["🐱 Киси Кошке: Суролан — 1,644₽"]

    async def test_category_equals_description_no_duplicate(self, db_session):
        db_session.add(User(telegram_id=1001))
        cat = Category(telegram_id=1001, name="🚌 Транспорт", keywords="[]")
        db_session.add(cat)
        await db_session.flush()
        db_session.add(
            Expense(
                telegram_id=1001,
                amount=83.0,
                description="транспорт",
                category_id=cat.id,
                date=get_msk_now(),
            )
        )
        await db_session.commit()

        lines = await get_today_expenses_grouped(1001)
        assert lines == ["🚌 Транспорт — 83₽"]


class TestEveningTeaser:
    def test_uses_blockquote_not_literal_arrows(self):
        from src.services.evening_report import _build_teaser

        text = _build_teaser(["🚌 Транспорт: метро — 83₽"], "10 ноября")

        assert "<blockquote>" in text
        assert "</blockquote>" in text
        assert "> Сегодня" not in text
        assert "Сегодня, 10 ноября:" in text

    def test_empty_lines_returns_initial(self):
        from src.services.evening_report import INITIAL_TEXT, _build_teaser

        assert _build_teaser([], "10 ноября") == INITIAL_TEXT


class TestPhraseCleanup:
    def test_welcome_menu_removed(self):
        assert not hasattr(phrases, "WELCOME_MENU")
        import src.bot.handlers.menu as menu

        assert "WELCOME_MENU" not in inspect.getsource(menu)

    def test_no_grechka(self):
        import src.utils.phrases as p

        assert "гречк" not in inspect.getsource(p).lower()


class TestMonthlyKeyboard:
    def test_refresh_on_separate_row(self):
        kb = get_monthly_nav_keyboard(True, True, "01.08–31.08", "01.10–31.10")

        nav_row, refresh_row = kb.inline_keyboard
        assert nav_row[0].callback_data == "monthly_prev"
        assert nav_row[1].callback_data == "monthly_next"
        assert [b.callback_data for b in refresh_row] == ["monthly_refresh"]

    def test_button_text_has_only_period(self):
        kb = get_monthly_nav_keyboard(True, False, "01.08–31.08")
        text = kb.inline_keyboard[0][0].text
        assert "01.08–31.08" in text
        assert "₽" not in text

    def test_single_nav_button_still_has_refresh_row(self):
        kb = get_monthly_nav_keyboard(False, True, "", "01.10–31.10")
        assert len(kb.inline_keyboard[0]) == 1
        assert kb.inline_keyboard[1][0].callback_data == "monthly_refresh"
