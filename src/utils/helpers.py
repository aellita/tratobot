import html
import math
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import emoji

from . import phrases

MAX_RETRIES = 3
MSK_TZ = ZoneInfo("Europe/Moscow")

FALLBACK_EMOJI = "🏷️"


def check_retry(retries: int) -> tuple[bool, int]:
    next_retry = retries + 1
    return next_retry >= MAX_RETRIES, next_retry


# --- Math expression evaluator (recursive descent, no eval) ---

_TOKEN_SPEC = [
    ("NUMBER", r"\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?"),
    ("PLUS", r"\+"),
    ("MINUS", r"-"),
    ("MUL", r"\*"),
    ("DIV", r"/"),
    ("LPAREN", r"\("),
    ("RPAREN", r"\)"),
]


class _MathParseError(Exception):
    pass


class _MathTokens:
    def __init__(self, text: str):
        self.tokens: list[tuple[str, str, int, int]] = []
        pos = 0
        while pos < len(text):
            if text[pos] in " \t":
                pos += 1
                continue
            matched = False
            for tok_type, pattern in _TOKEN_SPEC:
                m = re.match(pattern, text[pos:])
                if m:
                    raw = m.group(0)
                    val = raw.replace(",", ".")
                    self.tokens.append((tok_type, val, pos, pos + len(raw)))
                    pos += len(raw)
                    matched = True
                    break
            if not matched:
                break
        self.tokens.append(("EOF", "", pos, pos))

    def __getitem__(self, idx: int) -> tuple[str, str, int, int]:
        return self.tokens[idx]

    def __len__(self) -> int:
        return len(self.tokens)


class _MathParser:
    def __init__(self, tokens: _MathTokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> str:
        return self.tokens[self.pos][0]

    def consume(self, expected: str | None = None) -> str:
        if expected and self.peek() != expected:
            raise _MathParseError(f"Expected {expected}, got {self.peek()}")
        tok_type = self.tokens[self.pos][0]
        self.pos += 1
        return tok_type

    def consume_value(self) -> str:
        val = self.tokens[self.pos][1]
        self.pos += 1
        return val

    def at_end(self) -> bool:
        return self.peek() == "EOF"

    def current_text_end(self) -> int:
        return self.tokens[self.pos][2]

    def parse_expr(self) -> float:
        if self.peek() == "MINUS":
            self.consume()
            result = -self.parse_term()
        else:
            result = self.parse_term()
        while self.peek() in ("PLUS", "MINUS"):
            op_type = self.consume()
            right = self.parse_term()
            if op_type == "PLUS":
                result += right
            else:
                result -= right
        return result

    def parse_term(self) -> float:
        result = self.parse_factor()
        while self.peek() in ("MUL", "DIV"):
            op_type = self.consume()
            right = self.parse_factor()
            if op_type == "MUL":
                result *= right
            else:
                if right == 0:
                    raise ZeroDivisionError("division by zero")
                result /= right
        return result

    def parse_factor(self) -> float:
        if self.peek() == "PLUS":
            self.consume()
            return self.parse_factor()
        if self.peek() == "MINUS":
            self.consume()
            return -self.parse_factor()
        if self.peek() == "LPAREN":
            self.consume()
            result = self.parse_expr()
            self.consume("RPAREN")
            return result
        if self.peek() == "NUMBER":
            return float(self.consume_value())
        raise _MathParseError(f"Expected number or (, got {self.peek()}")


def _split_math_prefix(text: str) -> tuple[str, str] | None:
    """Split text into math-prefix and description. Returns None if no math tokens."""
    math_end = 0
    for m in re.finditer(r"\d+(?:[.,]\d+)?|[+\-*/()]", text):
        math_end = m.end()
    if math_end == 0:
        return None
    return text[:math_end], text[math_end:]


def _preprocess_math(text: str) -> tuple[str, bool, str | None]:
    """Auto-correct common math syntax errors. Returns (clean, was_corrected, hint)."""
    if not re.search(r"[+\-*/()]", text):
        return text, False, None

    parts = _split_math_prefix(text)
    if parts is None:
        return text, False, None
    math_part, desc_part = parts

    hint = None
    fixed_math = math_part

    # 1. Remove trailing operators (e.g. "500+300+" → "500+300")
    trailing_ops = re.search(r"[+\-*/]+$", fixed_math.rstrip())
    if trailing_ops:
        fixed_math = fixed_math[: trailing_ops.start()].rstrip()
        hint = phrases.HINT_TRAILING_OP

    # 2. Balance parentheses
    opens = fixed_math.count("(")
    closes = fixed_math.count(")")
    if opens > closes:
        fixed_math += ")" * (opens - closes)
        hint = phrases.HINT_CLOSED_PAREN
    elif closes > opens:
        extra = closes - opens
        for _ in range(extra):
            idx = fixed_math.rfind(")")
            if idx >= 0:
                fixed_math = fixed_math[:idx] + fixed_math[idx + 1:]
                hint = phrases.HINT_REMOVED_PAREN

    # 3. Collapse double operators (++ → +, +- → -, -+ → -)
    cleaned_ops = re.sub(r"\+\+", "+", fixed_math)
    cleaned_ops = re.sub(r"\+\-", "-", cleaned_ops)
    cleaned_ops = re.sub(r"-\+", "-", cleaned_ops)
    if cleaned_ops != fixed_math:
        fixed_math = cleaned_ops
        hint = phrases.HINT_DOUBLE_OPS

    fixed = fixed_math + desc_part
    if fixed == text:
        return text, False, None
    return fixed, True, hint


def _eval_math(text: str) -> float | None:
    if not re.search(r"[+\-*/]", text):
        return None
    try:
        tokens = _MathTokens(text)
        parser = _MathParser(tokens)
        result = parser.parse_expr()
        if not parser.at_end():
            return None
        return result
    except (_MathParseError, ZeroDivisionError, RecursionError):
        return None


def _parse_math_prefix(text: str) -> tuple[float, str] | None:
    if not re.search(r"[+\-*/()]", text):
        return None
    try:
        tokens = _MathTokens(text)
        parser = _MathParser(tokens)
        result = parser.parse_expr()
        end = parser.current_text_end()
        rest = text[end:].strip()
        return result, rest
    except (_MathParseError, ZeroDivisionError, RecursionError):
        return None


def get_msk_now() -> datetime:
    return datetime.now(MSK_TZ).replace(tzinfo=None)


def parse_amount(text: str, *, allow_zero: bool = False) -> float:
    math_result = _eval_math(text)
    if math_result is not None:
        amount = math_result
    else:
        clean = text.replace(" ", "").replace(",", ".")
        amount = float(clean)

    if not math.isfinite(amount):
        raise ValueError(f"Invalid amount: {amount}")
    if amount < 0:
        raise ValueError(f"Negative amount: {amount}")
    if amount >= 1e12:
        raise ValueError(f"Amount too large: {amount}")
    if not allow_zero and amount == 0:
        raise ValueError("Zero amount not allowed")
    return amount


def _extract_emoji(text: str) -> tuple[str | None, str]:
    if not text:
        return None, ""

    emojis = emoji.emoji_list(text)
    if not emojis:
        return None, text.strip()

    anchor = emojis[0]["emoji"]
    cleaned = emoji.replace_emoji(text, "")
    cleaned = " ".join(cleaned.split()).strip()

    return anchor, cleaned


def safe(text: str | None) -> str:
    return html.escape(text or "")


def parse_callback(data: str, expected_parts: int) -> list[str] | None:
    parts = data.split(":")
    return parts if len(parts) == expected_parts else None


def extract_callback_id(data: str, prefix: str) -> int | None:
    if not data.startswith(prefix):
        return None
    parts = parse_callback(data, 2)
    if parts is None:
        return None
    try:
        return int(parts[1])
    except (ValueError, TypeError):
        return None
