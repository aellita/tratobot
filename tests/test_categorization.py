import pytest
from src.services.categorization import (
    clean_and_normalize, get_category_display,
    _parse_keywords, _dump_keywords
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
