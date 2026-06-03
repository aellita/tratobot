import pytest
from src.utils.helpers import parse_amount, safe, parse_callback, extract_callback_id


class TestParseAmount:
    def test_simple_integer(self):
        assert parse_amount("300") == 300.0

    def test_with_spaces(self):
        assert parse_amount("1 000") == 1000.0

    def test_with_comma(self):
        assert parse_amount("99,90") == 99.9

    def test_with_dot(self):
        assert parse_amount("149.50") == 149.5

    def test_zero_allowed(self):
        assert parse_amount("0", allow_zero=True) == 0.0

    def test_zero_not_allowed(self):
        with pytest.raises(ValueError, match="Zero"):
            parse_amount("0")

    def test_negative_raises(self):
        with pytest.raises(ValueError, match="Negative"):
            parse_amount("-100")

    def test_infinity_raises(self):
        with pytest.raises(ValueError, match="Invalid"):
            parse_amount("inf")

    def test_nan_raises(self):
        with pytest.raises(ValueError, match="Invalid"):
            parse_amount("nan")

    def test_too_large_raises(self):
        with pytest.raises(ValueError, match="too large"):
            parse_amount("999999999999999")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            parse_amount("")

    def test_non_numeric_raises(self):
        with pytest.raises(ValueError):
            parse_amount("abc")

    def test_trailing_text_raises(self):
        with pytest.raises(ValueError):
            parse_amount("300 рублей")


class TestSafe:
    def test_escapes_html(self):
        assert safe("<script>") == "&lt;script&gt;"

    def test_escapes_quotes(self):
        assert safe('"hello"') == "&quot;hello&quot;"

    def test_escapes_ampersand(self):
        assert safe("a & b") == "a &amp; b"

    def test_none_returns_empty(self):
        assert safe(None) == ""

    def test_empty_string(self):
        assert safe("") == ""

    def test_normal_text_unchanged(self):
        assert safe("hello world") == "hello world"

    def test_unicode_preserved(self):
        assert safe("кофе 300₽") == "кофе 300₽"


class TestParseCallback:
    def test_valid_two_parts(self):
        assert parse_callback("set_cat:5", 2) == ["set_cat", "5"]

    def test_valid_three_parts(self):
        assert parse_callback("set_cat:5:3", 3) == ["set_cat", "5", "3"]

    def test_wrong_parts_count(self):
        assert parse_callback("set_cat:5", 3) is None

    def test_empty_string(self):
        assert parse_callback("", 2) is None

    def test_single_part(self):
        assert parse_callback("use_savings", 2) is None

    def test_extra_parts(self):
        assert parse_callback("a:b:c:d", 2) is None


class TestExtractCallbackId:
    def test_valid_prefix_and_id(self):
        assert extract_callback_id("exp_del:5", "exp_del") == 5

    def test_wrong_prefix(self):
        assert extract_callback_id("exp_del:5", "set_cat") is None

    def test_non_numeric_id(self):
        assert extract_callback_id("exp_del:abc", "exp_del") is None

    def test_missing_id(self):
        assert extract_callback_id("exp_del:", "exp_del") is None

    def test_no_colon(self):
        assert extract_callback_id("use_savings", "use_savings") is None

    def test_negative_id(self):
        assert extract_callback_id("exp_del:-5", "exp_del") == -5
