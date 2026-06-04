from src.services.categorization import (
    _dump_keywords,
    _parse_keywords,
    clean_and_normalize,
    get_category_display,
)


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
        assert _parse_keywords('[]') == []

    def test_empty_string(self):
        assert _parse_keywords('') == []

    def test_invalid_json(self):
        assert _parse_keywords('{invalid}') == []

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
        assert _dump_keywords([]) == '[]'

    def test_with_emoji(self):
        result = _dump_keywords(["🍔", "еда"])
        assert "🍔" in result
        assert "еда" in result

    def test_special_chars(self):
        result = _dump_keywords(["a'b", 'c"d'])
        assert '"a\\\'b"' in result or '"a\'b"' in result
        assert result is not None
