import html
import math


MAX_RETRIES = 3


def parse_amount(text: str, *, allow_zero: bool = False) -> float:
    clean = text.replace(" ", "").replace(",", ".")
    amount = float(clean)
    if not math.isfinite(amount):
        raise ValueError(f"Invalid amount: {amount}")
    if amount < 0:
        raise ValueError(f"Negative amount: {amount}")
    if amount >= 1e12:
        raise ValueError(f"Amount too large: {amount}")
    if not allow_zero and amount == 0:
        raise ValueError(f"Zero amount not allowed")
    return amount


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
