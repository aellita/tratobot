from src.db.models.models import Expense
from src.services.categorization import (
    _autocorrect_description,
    _dump_keywords,
    _get_keyword_avg,
    _parse_keywords,
    _score_by_keyword_avg,
    clean_and_normalize,
    detect_category_db,
    get_category_display,
    seed_user_categories,
)
from src.utils.helpers import get_msk_now


class TestCleanAndNormalize:
    def test_lowercases(self):
        assert clean_and_normalize("Кофе") == "кофе"

    def test_strips_whitespace(self):
        assert clean_and_normalize("  кофе  ") == "кофе"

    def test_already_clean(self):
        assert clean_and_normalize("кофе") == "кофе"

    def test_empty_string(self):
        assert clean_and_normalize("") == ""

    def test_mixed_case(self):
        assert clean_and_normalize("МакДоналдс") == "макдоналдс"

    def test_only_numbers(self):
        assert clean_and_normalize("123") == "123"

    def test_newline_stripped(self):
        assert clean_and_normalize("  кофе\n  ") == "кофе"


class TestGetCategoryDisplay:
    def test_known_category_returns_emoji(self):
        emoji, name = get_category_display("Еда")
        assert emoji == "🍔"
        assert name == "Еда"

    def test_case_insensitive(self):
        emoji, name = get_category_display("еда")
        assert emoji == "🍔"
        assert name == "Еда"

    def test_unknown_category_returns_fallback(self):
        emoji, name = get_category_display("Неизвестная")
        assert emoji == "📦"
        assert name == "Неизвестная"

    def test_transport_category(self):
        emoji, name = get_category_display("Транспорт")
        assert emoji == "🚌"
        assert name == "Транспорт"

    def test_empty_string(self):
        emoji, name = get_category_display("")
        assert emoji == "📦"
        assert name == ""

    def test_leading_trailing_spaces(self):
        emoji, name = get_category_display("  Еда  ")
        assert emoji == "🍔"
        assert name == "Еда"

    def test_all_caps(self):
        emoji, name = get_category_display("ЕДА")
        assert emoji == "🍔"
        assert name == "Еда"


class TestParseKeywords:
    def test_valid_json(self):
        assert _parse_keywords('["кофе", "чай"]') == ["кофе", "чай"]

    def test_empty_json(self):
        assert _parse_keywords("[]") == []

    def test_empty_string(self):
        assert _parse_keywords("") == []

    def test_invalid_json(self):
        assert _parse_keywords("{invalid}") == []

    def test_none(self):
        assert _parse_keywords(None) == []

    def test_unicode(self):
        assert _parse_keywords('["кофе", "обед"]') == ["кофе", "обед"]

    def test_very_long_json(self):
        long = ["word"] * 1000
        import json

        result = _parse_keywords(json.dumps(long))
        assert len(result) == 1000

    def test_nested_json_returns_whatever_json_loads(self):
        assert _parse_keywords('{"key": "value"}') == {"key": "value"}


class TestDumpKeywords:
    def test_basic_list(self):
        result = _dump_keywords(["кофе", "чай"])
        assert result == '["кофе", "чай"]'

    def test_empty_list(self):
        assert _dump_keywords([]) == "[]"

    def test_with_emoji(self):
        result = _dump_keywords(["🍔", "еда"])
        assert "🍔" in result
        assert "еда" in result

    def test_special_chars(self):
        result = _dump_keywords(["a'b", 'c"d'])
        assert '"a\\\'b"' in result or '"a\'b"' in result
        assert result is not None


class TestAutocorrectDescription:
    def test_no_typo(self):
        keywords = {"самокат", "такси", "метро"}
        assert _autocorrect_description("самокат", keywords) == "самокат"

    def test_typo_corrected(self):
        keywords = {"самокат", "такси"}
        assert _autocorrect_description("самокад", keywords) == "самокат"

    def test_close_typo_corrected(self):
        keywords = {"кофе", "кафе"}
        assert _autocorrect_description("кофе", keywords) == "кофе"

    def test_unknown_word_unchanged(self):
        keywords = {"такси", "метро"}
        assert _autocorrect_description("самолет", keywords) == "самолет"

    def test_multi_word_preserves_order(self):
        keywords = {"яндекс", "самокат", "еда"}
        assert _autocorrect_description("яндекс самокат", keywords) == "яндекс самокат"

    def test_empty_string(self):
        assert _autocorrect_description("", {"а"}) == ""

    def test_case_insensitive(self):
        keywords = {"самокат"}
        assert _autocorrect_description("СамокаТ", keywords) == "самокат"

    def test_distant_word_unchanged(self):
        keywords = {"самокат"}
        assert _autocorrect_description("автомобиль", keywords) == "автомобиль"

    def test_partial_match_in_multi_word(self):
        keywords = {"самокат", "доставка"}
        result = _autocorrect_description("самокат доставка", keywords)
        assert result == "самокат доставка"

    def test_boundary_cutoff_85_fixes_typo(self):
        keywords = {"самокат"}
        result = _autocorrect_description("самокад", keywords, cutoff=0.85)
        assert result == "самокат"

    def test_boundary_cutoff_85_rejects_distant(self):
        keywords = {"самокат"}
        result = _autocorrect_description("такси", keywords, cutoff=0.85)
        assert result == "такси"


class TestKeywordAvg:
    async def test_avg_from_single_expense(self, db_session, test_user):
        cats = await seed_user_categories(test_user.telegram_id)
        transport = [c for c in cats if c.name == "Транспорт"][0]
        now = get_msk_now()
        db_session.add(Expense(
            telegram_id=test_user.telegram_id, amount=200.0,
            description="самокат", category_id=transport.id,
            date=now, is_deleted=False,
        ))
        await db_session.commit()

        avg = await _get_keyword_avg(test_user.telegram_id, "самокат", transport.id)
        assert avg == 200.0

    async def test_avg_from_multiple_expenses(self, db_session, test_user):
        cats = await seed_user_categories(test_user.telegram_id)
        transport = [c for c in cats if c.name == "Транспорт"][0]
        now = get_msk_now()
        for amt in [200, 300, 400]:
            db_session.add(Expense(
                telegram_id=test_user.telegram_id, amount=amt,
                description="самокат", category_id=transport.id,
                date=now, is_deleted=False,
            ))
        await db_session.commit()

        avg = await _get_keyword_avg(test_user.telegram_id, "самокат", transport.id)
        assert avg == 300.0

    async def test_avg_respects_last_10_limit(self, db_session, test_user):
        from datetime import timedelta
        cats = await seed_user_categories(test_user.telegram_id)
        transport = [c for c in cats if c.name == "Транспорт"][0]
        now = get_msk_now()
        for i in range(15):
            db_session.add(Expense(
                telegram_id=test_user.telegram_id, amount=float(i * 100),
                description="самокат", category_id=transport.id,
                date=now + timedelta(seconds=i), is_deleted=False,
            ))
        await db_session.commit()

        avg = await _get_keyword_avg(test_user.telegram_id, "самокат", transport.id)
        assert avg == 950.0

    async def test_avg_excludes_deleted(self, db_session, test_user):
        cats = await seed_user_categories(test_user.telegram_id)
        transport = [c for c in cats if c.name == "Транспорт"][0]
        now = get_msk_now()
        db_session.add(Expense(
            telegram_id=test_user.telegram_id, amount=100.0,
            description="самокат", category_id=transport.id,
            date=now, is_deleted=False,
        ))
        db_session.add(Expense(
            telegram_id=test_user.telegram_id, amount=9999.0,
            description="самокат", category_id=transport.id,
            date=now, is_deleted=True,
        ))
        await db_session.commit()

        avg = await _get_keyword_avg(test_user.telegram_id, "самокат", transport.id)
        assert avg == 100.0

    async def test_avg_none_when_no_history(self, db_session, test_user):
        cats = await seed_user_categories(test_user.telegram_id)
        transport = [c for c in cats if c.name == "Транспорт"][0]
        avg = await _get_keyword_avg(test_user.telegram_id, "самокат", transport.id)
        assert avg is None

    async def test_avg_excludes_other_keywords(self, db_session, test_user):
        cats = await seed_user_categories(test_user.telegram_id)
        transport = [c for c in cats if c.name == "Транспорт"][0]
        cafe = [c for c in cats if c.name == "Кафе"][0]
        now = get_msk_now()
        db_session.add(Expense(
            telegram_id=test_user.telegram_id, amount=200.0,
            description="самокат", category_id=transport.id,
            date=now, is_deleted=False,
        ))
        db_session.add(Expense(
            telegram_id=test_user.telegram_id, amount=999.0,
            description="кофе", category_id=cafe.id,
            date=now, is_deleted=False,
        ))
        await db_session.commit()

        avg = await _get_keyword_avg(test_user.telegram_id, "самокат", transport.id)
        assert avg == 200.0


class TestCategoryScoring:
    async def _create_categories(self, telegram_id, db_session):
        cats = await seed_user_categories(telegram_id)
        eda = [c for c in cats if c.name == "Еда"][0]
        cafe = [c for c in cats if c.name == "Кафе"][0]
        return eda, cafe

    async def _add_expense(self, db_session, telegram_id, amount, desc, cat_id):
        db_session.add(Expense(
            telegram_id=telegram_id, amount=amount,
            description=desc, category_id=cat_id,
            date=get_msk_now(), is_deleted=False,
        ))
        await db_session.commit()

    async def test_scoring_picks_closer_category(self, db_session, test_user):
        telegram_id = test_user.telegram_id
        eda, cafe = await self._create_categories(telegram_id, db_session)
        await self._add_expense(db_session, telegram_id, 200, "кофе", eda.id)
        await self._add_expense(db_session, telegram_id, 500, "кофе", cafe.id)
        candidates = [(eda, "кофе"), (cafe, "кофе")]

        cat, kw = await _score_by_keyword_avg(telegram_id, candidates, 300)
        assert cat.id == eda.id

        cat, kw = await _score_by_keyword_avg(telegram_id, candidates, 600)
        assert cat.id == cafe.id

    async def test_scoring_returns_none_when_all_no_history(self, db_session, test_user):
        telegram_id = test_user.telegram_id
        eda, cafe = await self._create_categories(telegram_id, db_session)
        candidates = [(eda, "кофе"), (cafe, "кофе")]
        result = await _score_by_keyword_avg(telegram_id, candidates, 300)
        assert result is None

    async def test_detect_category_without_amount_picks_first(self, db_session, test_user):
        telegram_id = test_user.telegram_id
        await seed_user_categories(telegram_id)
        cat, kw = await detect_category_db("кофе", telegram_id, current_amount=0)
        assert cat is not None
        assert kw is not None

    async def test_autocorrect_before_categorization(self, db_session, test_user):
        telegram_id = test_user.telegram_id
        cats = await seed_user_categories(telegram_id)
        transport = [c for c in cats if c.name == "Транспорт"][0]
        await self._add_expense(db_session, telegram_id, 200, "самокат", transport.id)
        cat, kw = await detect_category_db("самокад", telegram_id, current_amount=200)
        assert cat is not None
        assert cat.name == "Транспорт"

    async def test_homonym_scoring_integration(self, db_session, test_user):
        telegram_id = test_user.telegram_id
        eda, cafe = await self._create_categories(telegram_id, db_session)
        await self._add_expense(db_session, telegram_id, 200, "кофе", eda.id)
        await self._add_expense(db_session, telegram_id, 500, "кофе", cafe.id)

        cat, kw = await detect_category_db("кофе", telegram_id, current_amount=300)
        assert cat.id == eda.id

        cat, kw = await detect_category_db("кофе", telegram_id, current_amount=600)
        assert cat.id == cafe.id

    async def test_unique_keyword_fast_path_no_scoring(self, db_session, test_user):
        telegram_id = test_user.telegram_id
        cats = await seed_user_categories(telegram_id)
        transport = [c for c in cats if c.name == "Транспорт"][0]
        await self._add_expense(db_session, telegram_id, 200, "метро", transport.id)
        cat, kw = await detect_category_db("метро", telegram_id, current_amount=9999)
        assert cat.name == "Транспорт"
