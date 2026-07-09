from src.services.expense_service import (
    clean_description,
    parse_expense_text,
    parse_multi_expense_text,
)


class TestParseExpenseText:
    def _check(self, result, expected_amount, expected_desc_substr):
        assert result.is_valid, f"Expected valid, got error_type={result.error_type}, text={result.raw_text!r}"
        assert result.amount == expected_amount
        assert expected_desc_substr in result.description, \
            f"Expected {expected_desc_substr!r} in {result.description!r}"

    def test_simple_amount_and_description(self):
        self._check(parse_expense_text("300 кофе"), 300.0, "кофе")

    def test_amount_with_ruble_symbol(self):
        self._check(parse_expense_text("500₽ обед"), 500.0, "обед")

    def test_amount_with_ruble_word(self):
        result = parse_expense_text("1000 рублей такси")
        self._check(result, 1000.0, "такси")
        assert "рублей" not in result.description

    def test_decimal_amount_with_comma(self):
        self._check(parse_expense_text("99,90 пирожок"), 99.9, "пирожок")

    def test_decimal_amount_with_dot(self):
        self._check(parse_expense_text("149.50 обед"), 149.5, "обед")

    def test_multiline_parsed_as_single_line(self):
        self._check(parse_expense_text("300 кофе"), 300.0, "кофе")

    def test_takes_first_number_not_sum(self):
        result = parse_expense_text("500 кофе 300 пирожок")
        self._check(result, 500.0, "кофе")

    def test_no_numbers_returns_invalid(self):
        result = parse_expense_text("кофе")
        assert not result.is_valid
        assert result.error_type == "NO_NUMBER"

    def test_empty_string_returns_invalid(self):
        result = parse_expense_text("")
        assert not result.is_valid
        assert result.error_type == "EMPTY"

    def test_only_whitespace_returns_invalid(self):
        result = parse_expense_text("   ")
        assert not result.is_valid
        assert result.error_type == "EMPTY"

    def test_amount_with_plus_trailing(self):
        result = parse_expense_text("300+кофе")
        assert result.is_valid, f"Expected valid, got {result.error_type}"
        assert result.amount == 300.0
        assert result.was_corrected  # trailing + was removed

    def test_negative_amount_ignored_first_positive_taken(self):
        result = parse_expense_text("-100 500 кофе")
        assert not result.is_valid
        assert result.error_type == "MATH_ERROR"

    def test_zero_amount_ignored(self):
        result = parse_expense_text("0 300 кофе")
        self._check(result, 300.0, "кофе")

    def test_large_amount(self):
        self._check(parse_expense_text("999999 кофе"), 999999.0, "кофе")

    def test_leading_zeros(self):
        self._check(parse_expense_text("000300 кофе"), 300.0, "кофе")

    def test_number_in_middle_of_word(self):
        result = parse_expense_text("кофе300обед")
        self._check(result, 300.0, "кофе")

    def test_emoji_in_description(self):
        result = parse_expense_text("300 кофе ☕️")
        self._check(result, 300.0, "кофе")
        assert "☕️" in result.description or "☕" in result.description

    def test_multiple_decimal_dots_takes_first_segment(self):
        self._check(parse_expense_text("3.00.50 кофе"), 3.0, "кофе")

    def test_tab_separated(self):
        result = parse_expense_text("300\tкофе")
        self._check(result, 300.0, "кофе")
        assert result.description == "кофе"

    def test_just_a_number_no_description(self):
        result = parse_expense_text("300")
        self._check(result, 300.0, "")
        assert result.description == ""

    def test_number_at_end_after_description(self):
        self._check(parse_expense_text("кофе 300"), 300.0, "кофе")

    def test_number_with_trailing_comma(self):
        self._check(parse_expense_text("300, кофе"), 300.0, "кофе")

    def test_unicode_minus_sign_not_parsed_by_regex(self):
        result = parse_expense_text("\u2212300 500 кофе")
        self._check(result, 300.0, "кофе")

    def test_only_special_chars_returns_invalid(self):
        result = parse_expense_text("@#$%")
        assert not result.is_valid
        assert result.error_type == "NO_NUMBER"

    def test_description_with_only_numbers(self):
        self._check(parse_expense_text("300 500 700"), 300.0, "")

    def test_math_expression_correct(self):
        result = parse_expense_text("500+300 кофе")
        self._check(result, 800.0, "кофе")
        assert not result.was_corrected

    def test_math_missing_paren_corrected(self):
        result = parse_expense_text("(500+300 кофе")
        assert result.is_valid
        assert result.amount == 800.0
        assert result.was_corrected
        assert result.correction_hint is not None

    def test_math_extra_paren_corrected(self):
        result = parse_expense_text("500+300) кофе")
        assert result.is_valid
        assert result.amount == 800.0
        assert "кофе" in result.description
        assert ")" not in result.description
        assert result.was_corrected

    def test_math_stray_paren_corrected(self):
        result = parse_expense_text("1+1)")
        assert result.is_valid
        assert result.amount == 2.0
        assert result.was_corrected

    def test_math_trailing_op_corrected(self):
        result = parse_expense_text("500+300+ кофе")
        assert result.is_valid
        assert result.amount == 800.0
        assert result.was_corrected

    def test_math_negative_result_returns_invalid(self):
        result = parse_expense_text("(7+2)-20")
        assert not result.is_valid
        assert result.error_type == "MATH_ERROR"
        assert "отрицательная" in result.error_detail

    def test_math_negative_result_with_desc_returns_invalid(self):
        result = parse_expense_text("(7+2)-20 кофе")
        assert not result.is_valid
        assert result.error_type == "MATH_ERROR"
        assert "отрицательная" in result.error_detail

    def test_math_zero_result_returns_invalid(self):
        result = parse_expense_text("5-5")
        assert not result.is_valid
        assert result.error_type == "MATH_ERROR"
        assert "нулевая" in result.error_detail

    def test_math_zero_result_mul_returns_invalid(self):
        result = parse_expense_text("5*0")
        assert not result.is_valid
        assert result.error_type == "MATH_ERROR"
        assert "нулевая" in result.error_detail

    def test_sci_notation_standalone(self):
        result = parse_expense_text("1e5")
        assert result.is_valid
        assert result.amount == 100000.0

    def test_sci_notation_with_desc(self):
        result = parse_expense_text("1e5 кофе")
        assert result.is_valid
        assert result.amount == 100000.0
        assert "кофе" in result.description

    def test_sci_notation_in_math(self):
        result = parse_expense_text("1e5+2e5")
        assert result.is_valid
        assert result.amount == 300000.0

    def test_sci_notation_in_math_with_desc(self):
        result = parse_expense_text("1e5+2e5 донат")
        assert result.is_valid
        assert result.amount == 300000.0
        assert "донат" in result.description

    def test_sci_notation_negative_exponent(self):
        result = parse_expense_text("5e-3")
        assert result.is_valid
        assert result.amount == 0.005

    def test_sci_notation_capital_e(self):
        result = parse_expense_text("2E5")
        assert result.is_valid
        assert result.amount == 200000.0

    def test_sci_notation_plus_exponent(self):
        result = parse_expense_text("3e+4")
        assert result.is_valid
        assert result.amount == 30000.0

    def test_div_by_zero_returns_invalid(self):
        result = parse_expense_text("500/0 халява")
        assert not result.is_valid
        assert result.error_type == "MATH_ERROR"

    def test_math_garbage_corrected(self):
        result = parse_expense_text("500+abc")
        assert result.is_valid
        assert result.amount == 500.0
        assert "abc" in result.description
        assert result.was_corrected

    def test_math_incomplete_corrected(self):
        result = parse_expense_text("500+")
        assert result.is_valid
        assert result.amount == 500.0
        assert result.was_corrected


class TestParseMultiExpenseText:
    def test_two_lines(self):
        result = parse_multi_expense_text("300 кофе\n500 обед")
        assert result.is_fully_valid
        assert len(result.reports) == 2
        assert result.reports[0].amount == 300.0
        assert result.reports[1].amount == 500.0

    def test_three_lines_with_empty(self):
        result = parse_multi_expense_text("100 такси\n\n200 аптека")
        assert result.is_fully_valid
        assert len(result.reports) == 2

    def test_line_with_no_number_skipped(self):
        result = parse_multi_expense_text("300 кофе\nпросто текст")
        assert result.is_fully_valid
        assert len(result.reports) == 1
        assert result.reports[0].is_valid

    def test_empty_text_returns_empty(self):
        result = parse_multi_expense_text("")
        assert result.is_fully_valid
        assert len(result.reports) == 0

    def test_whitespace_only_returns_empty(self):
        result = parse_multi_expense_text("   \n  \n  ")
        assert result.is_fully_valid
        assert len(result.reports) == 0

    def test_trailing_newline(self):
        result = parse_multi_expense_text("300 кофе\n")
        assert result.is_fully_valid
        assert len(result.reports) == 1
        assert result.reports[0].amount == 300.0

    def test_mixed_delimiters(self):
        result = parse_multi_expense_text("300 кофе\n500 обед\n200+ужин")
        # "200+ужин" gets corrected (trailing + removed)
        assert result.is_fully_valid
        assert len(result.reports) == 3
        assert result.reports[2].amount == 200.0
        assert result.reports[2].was_corrected

    def test_windows_line_endings(self):
        result = parse_multi_expense_text("300 кофе\r\n500 обед")
        assert result.is_fully_valid
        assert len(result.reports) == 2

    def test_leading_newline(self):
        result = parse_multi_expense_text("\n300 кофе")
        assert result.is_fully_valid
        assert len(result.reports) == 1

    def test_all_lines_no_numbers(self):
        result = parse_multi_expense_text("просто текст\nещё текст")
        assert result.is_fully_valid
        assert len(result.reports) == 0

    def test_math_error_blocks_all(self):
        result = parse_multi_expense_text("300 кофе\n500/0 обед\n200 такси")
        assert not result.is_fully_valid
        assert result.reports[0].is_valid
        assert not result.reports[1].is_valid
        assert result.reports[1].error_type == "MATH_ERROR"
        assert result.reports[2].is_valid


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
