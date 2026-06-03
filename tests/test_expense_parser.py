import pytest
from src.services.expense_service import parse_expense_text, parse_multi_expense_text, clean_description


class TestParseExpenseText:
    def test_simple_amount_and_description(self):
        result = parse_expense_text("300 кофе")
        assert result is not None
        amount, desc = result
        assert amount == 300.0
        assert "кофе" in desc

    def test_amount_with_ruble_symbol(self):
        result = parse_expense_text("500₽ обед")
        assert result is not None
        amount, desc = result
        assert amount == 500.0
        assert "обед" in desc

    def test_amount_with_ruble_word(self):
        result = parse_expense_text("1000 рублей такси")
        assert result is not None
        amount, desc = result
        assert amount == 1000.0
        assert "такси" in desc
        assert "рублей" not in desc

    def test_decimal_amount_with_comma(self):
        result = parse_expense_text("99,90 пирожок")
        assert result is not None
        amount, desc = result
        assert amount == 99.9

    def test_decimal_amount_with_dot(self):
        result = parse_expense_text("149.50 обед")
        assert result is not None
        amount, desc = result
        assert amount == 149.5

    def test_multiline_parsed_as_single_line(self):
        result = parse_expense_text("300 кофе")
        assert result is not None
        amount, desc = result
        assert amount == 300.0
        assert "кофе" in desc

    def test_takes_first_number_not_sum(self):
        result = parse_expense_text("500 кофе 300 пирожок")
        assert result is not None
        amount, desc = result
        assert amount == 500.0
        assert "кофе" in desc

    def test_no_numbers_returns_none(self):
        result = parse_expense_text("кофе")
        assert result is None

    def test_empty_string_returns_none(self):
        result = parse_expense_text("")
        assert result is None

    def test_only_whitespace_returns_none(self):
        result = parse_expense_text("   ")
        assert result is None

    def test_amount_with_plus(self):
        result = parse_expense_text("300+кофе")
        assert result is not None
        amount, desc = result
        assert amount == 300.0

    def test_negative_amount_ignored_first_positive_taken(self):
        result = parse_expense_text("-100 500 кофе")
        assert result is not None
        amount, desc = result
        assert amount == 100.0

    def test_zero_amount_ignored(self):
        result = parse_expense_text("0 300 кофе")
        assert result is not None
        amount, desc = result
        assert amount == 300.0

    def test_large_amount(self):
        result = parse_expense_text("999999 кофе")
        assert result is not None
        amount, desc = result
        assert amount == 999999.0

    def test_leading_zeros(self):
        result = parse_expense_text("000300 кофе")
        assert result is not None
        amount, desc = result
        assert amount == 300.0

    def test_number_in_middle_of_word(self):
        result = parse_expense_text("кофе300обед")
        assert result is not None
        amount, desc = result
        assert amount == 300.0
        assert "кофе" in desc

    def test_emoji_in_description(self):
        result = parse_expense_text("300 кофе ☕️")
        assert result is not None
        amount, desc = result
        assert amount == 300.0
        assert "☕️" in desc or "☕" in desc

    def test_multiple_decimal_dots_takes_first_segment(self):
        result = parse_expense_text("3.00.50 кофе")
        assert result is not None
        amount, desc = result
        assert amount == 3.0

    def test_tab_separated(self):
        result = parse_expense_text("300\tкофе")
        assert result is not None
        amount, desc = result
        assert amount == 300.0
        assert desc == "кофе"

    def test_just_a_number_no_description(self):
        result = parse_expense_text("300")
        assert result is not None
        amount, desc = result
        assert amount == 300.0
        assert desc == ""

    def test_number_at_end_after_description(self):
        result = parse_expense_text("кофе 300")
        assert result is not None
        amount, desc = result
        assert amount == 300.0

    def test_number_with_trailing_comma(self):
        result = parse_expense_text("300, кофе")
        assert result is not None
        amount, desc = result
        assert amount == 300.0
        assert "кофе" in desc

    def test_unicode_minus_sign_not_parsed_by_regex(self):
        result = parse_expense_text("\u2212300 500 кофе")
        assert result is not None
        amount, desc = result
        assert amount == 300.0

    def test_only_special_chars_returns_none(self):
        result = parse_expense_text("@#$%")
        assert result is None

    def test_description_with_only_numbers(self):
        result = parse_expense_text("300 500 700")
        assert result is not None
        amount, desc = result
        assert amount == 300.0


class TestParseMultiExpenseText:
    def test_two_lines(self):
        result = parse_multi_expense_text("300 кофе\n500 обед")
        assert len(result) == 2
        assert result[0] == (300.0, "кофе")
        assert result[1] == (500.0, "обед")

    def test_three_lines_with_empty(self):
        result = parse_multi_expense_text("100 такси\n\n200 аптека")
        assert len(result) == 2
        assert result[0] == (100.0, "такси")
        assert result[1] == (200.0, "аптека")

    def test_line_with_no_number_skipped(self):
        result = parse_multi_expense_text("300 кофе\nпросто текст")
        assert len(result) == 1
        assert result[0] == (300.0, "кофе")

    def test_empty_text_returns_empty_list(self):
        result = parse_multi_expense_text("")
        assert result == []

    def test_whitespace_only_returns_empty_list(self):
        result = parse_multi_expense_text("   \n  \n  ")
        assert result == []

    def test_trailing_newline(self):
        result = parse_multi_expense_text("300 кофе\n")
        assert len(result) == 1
        assert result[0] == (300.0, "кофе")

    def test_mixed_delimiters(self):
        result = parse_multi_expense_text("300 кофе\n500 обед\n200+ужин")
        assert len(result) == 3
        assert result[2] == (200.0, "ужин")

    def test_windows_line_endings(self):
        result = parse_multi_expense_text("300 кофе\r\n500 обед")
        assert len(result) == 2
        assert result[0] == (300.0, "кофе")
        assert result[1] == (500.0, "обед")

    def test_many_lines(self):
        text = "\n".join(f"{i*100} расход{i}" for i in range(1, 21))
        result = parse_multi_expense_text(text)
        assert len(result) == 20
        assert result[0] == (100.0, "расход1")

    def test_leading_newline(self):
        result = parse_multi_expense_text("\n300 кофе")
        assert len(result) == 1

    def test_all_lines_no_numbers(self):
        result = parse_multi_expense_text("просто текст\nещё текст")
        assert result == []


class TestCleanDescription:
    def test_removes_ruble_words(self):
        assert clean_description("кофе рублей") == "кофе"
        assert clean_description("обед рубля") == "обед"
        assert clean_description("такси рубль") == "такси"

    def test_removes_ruble_symbol(self):
        assert clean_description("кофе 300 ₽") == "кофе 300 ₽"

    def test_removes_standalone_r(self):
        assert clean_description("кофе р") == "кофе"

    def test_collapses_spaces(self):
        assert clean_description("кофе    обед") == "кофе обед"

    def test_collapses_plus(self):
        assert clean_description("кофе+обед") == "кофе обед"

    def test_truncates_to_500_chars(self):
        long = "а" * 600
        result = clean_description(long)
        assert len(result) == 500

    def test_strips_whitespace(self):
        assert clean_description("  кофе  ") == "кофе"

    def test_removes_multiple_ruble_variants(self):
        assert clean_description("обед рубль рубля рублей") == "обед"

    def test_empty_text(self):
        assert clean_description("") == ""

    def test_only_ignore_words(self):
        assert clean_description("рублей рубля рубль") == ""

    def test_already_escaped_html_preserved(self):
        assert clean_description("&lt;script&gt;") == "&lt;script&gt;"

    def test_only_emoji(self):
        assert clean_description("😊") == "😊"

    def test_only_spaces_becomes_empty(self):
        assert clean_description("   ") == ""

    def test_tab_replaced_with_space(self):
        assert clean_description("кофе\tобед") == "кофе обед"

    def test_newline_replaced_with_space(self):
        assert clean_description("кофе\nобед") == "кофе обед"

    def test_underscore_preserved(self):
        assert clean_description("кофе_обед") == "кофе_обед"

    def test_exactly_500_chars(self):
        text = "а" * 500
        assert len(clean_description(text)) == 500

    def test_501_chars_truncated(self):
        text = "а" * 501
        assert len(clean_description(text)) == 500

    def test_mixed_scripts(self):
        result = clean_description("кофе300обед test")
        assert "кофе" in result
        assert "300" in result

    def test_plus_not_at_word_boundary(self):
        assert clean_description("кофе+") == "кофе"

    def test_no_alphabetic_only_spaces_and_tabs(self):
        assert clean_description("   \t  ") == ""
