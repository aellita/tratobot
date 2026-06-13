from unittest.mock import AsyncMock, MagicMock, patch

from src.db.models.models import Category
from src.services.category_service import rename_category
from src.utils.helpers import _extract_emoji


class TestExtractEmoji:
    def test_emoji_at_start(self):
        assert _extract_emoji("🍔 Еда") == ("🍔", "Еда")

    def test_no_emoji(self):
        assert _extract_emoji("Еда") == (None, "Еда")

    def test_emoji_at_end(self):
        assert _extract_emoji("Такси 🚕") == ("🚕", "Такси")

    def test_multiple_emoji_cleaned_from_text(self):
        assert _extract_emoji("⏰ 🚌 Транспорт") == ("⏰", "Транспорт")

    def test_flag_emoji(self):
        assert _extract_emoji("🇷🇺 Россия") == ("🇷🇺", "Россия")

    def test_emoji_attached_to_text(self):
        assert _extract_emoji("Кушанье🍔") == ("🍔", "Кушанье")

    def test_two_emoji_first_wins(self):
        assert _extract_emoji("🍔🎂 Десерты") == ("🍔", "Десерты")

    def test_empty_string(self):
        assert _extract_emoji("") == (None, "")

    def test_whitespace_only(self):
        assert _extract_emoji("   ") == (None, "")

    def test_only_emoji(self):
        assert _extract_emoji("🍔") == ("🍔", "")

    def test_only_multiple_emoji(self):
        anchor, text = _extract_emoji("🍔🎂")
        assert anchor == "🍔"
        assert text == ""

    def test_emoji_sandwich(self):
        assert _extract_emoji("Здоровье 💊💪") == ("💊", "Здоровье")

    def test_emoji_inside_word(self):
        assert _extract_emoji("a🍔b") == ("🍔", "ab")

    def test_no_emoji_special_chars(self):
        assert _extract_emoji("123 !@#") == (None, "123 !@#")

    def test_emoji_unicode_variation_selector(self):
        result = _extract_emoji("☕ Кофе")
        assert result[0] is not None
        assert result[1] == "Кофе"


class TestRenameCategoryService:
    async def test_rename_own_category(self, db_session):
        cat = Category(telegram_id=99999, name="Старое имя")
        db_session.add(cat)
        await db_session.commit()
        cat_id = cat.id

        result = await rename_category(99999, cat_id, "🍔 Новое имя")
        assert result is True

        await db_session.refresh(cat)
        assert cat.name == "🍔 Новое имя"

    async def test_rename_wrong_owner_returns_false(self, db_session):
        cat = Category(telegram_id=99999, name="Старое имя")
        db_session.add(cat)
        await db_session.commit()

        result = await rename_category(88888, cat.id, "🍔 Новое имя")
        assert result is False

    async def test_rename_nonexistent_returns_false(self):
        result = await rename_category(99999, 99999, "🍔 Новое имя")
        assert result is False

    async def test_rename_preserves_keywords(self, db_session):
        cat = Category(
            telegram_id=99999,
            name="🍔 Еда",
            keywords='["еда", "продукты"]',
        )
        db_session.add(cat)
        await db_session.commit()

        await rename_category(99999, cat.id, "🍔 Кушанье")

        await db_session.refresh(cat)
        assert cat.keywords == '["еда", "продукты"]'


def _make_message(text: str, user_id: int = 99999) -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.from_user.id = user_id
    msg.from_user.first_name = "Test"
    msg.from_user.username = "testuser"
    msg.chat.id = user_id
    msg.message_id = 1
    msg.bot = MagicMock()
    msg.bot.edit_message_reply_markup = AsyncMock()
    msg.answer = AsyncMock(return_value=msg)
    msg.delete = AsyncMock()
    return msg


def _make_state(**initial_data) -> AsyncMock:
    state = AsyncMock()
    state.get_data = AsyncMock(return_value=initial_data)
    return state


class TestProcessCatRenameHandler:
    @patch("src.bot.handlers.categories.get_main_menu_keyboard", AsyncMock())
    async def test_rename_without_emoji_keeps_old_anchor(self, db_session):
        cat = Category(telegram_id=99999, name="Еда")
        db_session.add(cat)
        await db_session.commit()
        cat_id = cat.id

        msg = _make_message("Кушанье")
        state = _make_state(cat_rename_id=cat_id)

        from src.bot.handlers.categories import process_cat_rename

        await process_cat_rename(msg, state)

        msg.answer.assert_awaited()
        call_text = msg.answer.call_args[1]["text"]
        assert "🍔 Кушанье" in call_text

        await db_session.refresh(cat)
        assert cat.name == "🍔 Кушанье"

    @patch("src.bot.handlers.categories.get_main_menu_keyboard", AsyncMock())
    async def test_rename_with_new_emoji_replaces_anchor(self, db_session):
        cat = Category(telegram_id=99999, name="Еда")
        db_session.add(cat)
        await db_session.commit()
        cat_id = cat.id

        msg = _make_message("🎂 Сладости")
        state = _make_state(cat_rename_id=cat_id)

        from src.bot.handlers.categories import process_cat_rename

        await process_cat_rename(msg, state)

        msg.answer.assert_awaited()
        call_text = msg.answer.call_args[1]["text"]
        assert "🎂 Сладости" in call_text

        await db_session.refresh(cat)
        assert cat.name == "🎂 Сладости"

    @patch("src.bot.handlers.categories.get_main_menu_keyboard", AsyncMock())
    async def test_rename_rename_keeps_current_anchor(self, db_session):
        cat = Category(telegram_id=99999, name="🍔 Кушанье")
        db_session.add(cat)
        await db_session.commit()
        cat_id = cat.id

        msg = _make_message("Кушать")
        state = _make_state(cat_rename_id=cat_id)

        from src.bot.handlers.categories import process_cat_rename

        await process_cat_rename(msg, state)

        msg.answer.assert_awaited()
        call_text = msg.answer.call_args[1]["text"]
        assert "🍔 Кушать" in call_text

    @patch("src.bot.handlers.categories.get_main_menu_keyboard", AsyncMock())
    async def test_rename_rename_with_new_emoji(self, db_session):
        cat = Category(telegram_id=99999, name="🍔 Кушанье")
        db_session.add(cat)
        await db_session.commit()
        cat_id = cat.id

        msg = _make_message("🎂 Десерты")
        state = _make_state(cat_rename_id=cat_id)

        from src.bot.handlers.categories import process_cat_rename

        await process_cat_rename(msg, state)

        msg.answer.assert_awaited()
        call_text = msg.answer.call_args[1]["text"]
        assert "🎂 Десерты" in call_text

    @patch("src.bot.handlers.categories.get_main_menu_keyboard", AsyncMock())
    async def test_emoji_at_end_of_input(self, db_session):
        cat = Category(telegram_id=99999, name="Транспорт")
        db_session.add(cat)
        await db_session.commit()
        cat_id = cat.id

        msg = _make_message("Такси 🚕")
        state = _make_state(cat_rename_id=cat_id)

        from src.bot.handlers.categories import process_cat_rename

        await process_cat_rename(msg, state)

        msg.answer.assert_awaited()
        call_text = msg.answer.call_args[1]["text"]
        assert "🚕 Такси" in call_text

    @patch("src.bot.handlers.categories.get_main_menu_keyboard", AsyncMock())
    async def test_duplicate_name_returns_error(self, db_session):
        cat_a = Category(telegram_id=99999, name="🚌 Еда")
        cat_b = Category(telegram_id=99999, name="Транспорт")
        db_session.add_all([cat_a, cat_b])
        await db_session.commit()

        msg = _make_message("Еда")
        state = _make_state(cat_rename_id=cat_b.id)

        from src.bot.handlers.categories import process_cat_rename

        await process_cat_rename(msg, state)

        msg.answer.assert_awaited()
        call_text = msg.answer.call_args[0][0]
        assert "уже существует" in call_text

    @patch("src.bot.handlers.categories.get_main_menu_keyboard", AsyncMock())
    async def test_empty_input_returns_error(self, db_session):
        cat = Category(telegram_id=99999, name="Еда")
        db_session.add(cat)
        await db_session.commit()

        msg = _make_message("")
        state = _make_state(cat_rename_id=cat.id)

        from src.bot.handlers.categories import process_cat_rename

        await process_cat_rename(msg, state)

        msg.answer.assert_awaited()
        call_text = msg.answer.call_args[0][0]
        assert "символов" in call_text

    @patch("src.bot.handlers.categories.get_main_menu_keyboard", AsyncMock())
    async def test_only_emoji_input_returns_error(self, db_session):
        cat = Category(telegram_id=99999, name="Еда")
        db_session.add(cat)
        await db_session.commit()

        msg = _make_message("🍔")
        state = _make_state(cat_rename_id=cat.id)

        from src.bot.handlers.categories import process_cat_rename

        await process_cat_rename(msg, state)

        msg.answer.assert_awaited()
        call_text = msg.answer.call_args[0][0]
        assert "символов" in call_text

    @patch("src.bot.handlers.categories.get_main_menu_keyboard", AsyncMock())
    async def test_too_long_input_returns_error(self, db_session):
        cat = Category(telegram_id=99999, name="Еда")
        db_session.add(cat)
        await db_session.commit()

        msg = _make_message("А" * 31)
        state = _make_state(cat_rename_id=cat.id)

        from src.bot.handlers.categories import process_cat_rename

        await process_cat_rename(msg, state)

        msg.answer.assert_awaited()
        call_text = msg.answer.call_args[0][0]
        assert "символов" in call_text

    @patch("src.bot.handlers.categories.get_main_menu_keyboard", AsyncMock())
    async def test_category_not_found_returns_error(self, db_session):
        msg = _make_message("Новое имя")
        state = _make_state(cat_rename_id=99999)

        from src.bot.handlers.categories import process_cat_rename

        await process_cat_rename(msg, state)

        msg.answer.assert_awaited()
        call_text = msg.answer.call_args[0][0]
        assert "не найдена" in call_text

    @patch("src.bot.handlers.categories.get_main_menu_keyboard", AsyncMock())
    async def test_same_name_noop(self, db_session):
        cat = Category(telegram_id=99999, name="🍔 Еда")
        db_session.add(cat)
        await db_session.commit()
        cat_id = cat.id

        msg = _make_message("Еда")
        state = _make_state(cat_rename_id=cat_id)

        from src.bot.handlers.categories import process_cat_rename

        await process_cat_rename(msg, state)

        msg.answer.assert_awaited()
        call_text = msg.answer.call_args[1]["text"]
        assert "Еда" in call_text

    @patch("src.bot.handlers.categories.get_main_menu_keyboard", AsyncMock())
    async def test_archived_category_can_be_renamed(self, db_session):
        cat = Category(telegram_id=99999, name="Старая", is_archived=True)
        db_session.add(cat)
        await db_session.commit()
        cat_id = cat.id

        msg = _make_message("Новое имя")
        state = _make_state(cat_rename_id=cat_id)

        from src.bot.handlers.categories import process_cat_rename

        await process_cat_rename(msg, state)

        msg.answer.assert_awaited()
        await db_session.refresh(cat)
        assert cat.name == "🏷️ Новое имя"
        assert cat.is_archived is True

    @patch("src.bot.handlers.categories.get_main_menu_keyboard", AsyncMock())
    async def test_user_category_without_default_emoji_gets_fallback(self, db_session):
        cat = Category(telegram_id=99999, name="Мои расходы")
        db_session.add(cat)
        await db_session.commit()
        cat_id = cat.id

        msg = _make_message("Мои траты")
        state = _make_state(cat_rename_id=cat_id)

        from src.bot.handlers.categories import process_cat_rename

        await process_cat_rename(msg, state)

        msg.answer.assert_awaited()
        call_text = msg.answer.call_args[1]["text"]
        assert "🏷️ Мои траты" in call_text

    @patch("src.bot.handlers.categories.get_main_menu_keyboard", AsyncMock())
    async def test_no_state_data_clears_and_returns(self):
        msg = _make_message("Новое имя")
        state = _make_state()

        from src.bot.handlers.categories import process_cat_rename

        await process_cat_rename(msg, state)

        state.clear.assert_awaited()
