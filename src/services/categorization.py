import difflib
import json

from sqlalchemy import func, select

from ..db.database import async_session_maker
from ..db.models.models import Category, Expense
from ..utils import phrases

_seeded_users: set[int] = set()


GREETINGS = phrases.GREETINGS

DEFAULT_CATEGORIES = phrases.DEFAULT_CATEGORIES

CATEGORY_EMOJI_MAP = {}
CATEGORY_NAME_MAP = {}
for display_name in DEFAULT_CATEGORIES:
    emoji = display_name.split()[0]
    name = " ".join(display_name.split()[1:])
    CATEGORY_EMOJI_MAP[name.lower()] = emoji
    CATEGORY_NAME_MAP[name.lower()] = name


def _parse_keywords(keywords_text: str) -> list[str]:
    try:
        return json.loads(keywords_text) if keywords_text else []
    except (json.JSONDecodeError, TypeError):
        return []


def _dump_keywords(keywords: list[str]) -> str:
    return json.dumps(keywords, ensure_ascii=False)


def clean_and_normalize(word: str) -> str:
    return word.strip().lower()


def _autocorrect_description(text: str, all_keywords: set[str], cutoff: float = 0.85) -> str:
    words = text.split()
    corrected = []
    for word in words:
        word_lower = word.lower()
        if word_lower in all_keywords:
            corrected.append(word_lower)
            continue
        matches = difflib.get_close_matches(word_lower, all_keywords, n=1, cutoff=cutoff)
        if matches:
            corrected.append(matches[0])
        else:
            corrected.append(word_lower)
    return " ".join(corrected)


async def _get_keyword_avg(telegram_id: int, keyword: str, category_id: int) -> float | None:
    async with async_session_maker() as session:
        subq = (
            select(Expense.amount)
            .where(
                Expense.telegram_id == telegram_id,
                Expense.category_id == category_id,
                Expense.is_deleted == False,
                Expense.description.contains(keyword),
            )
            .order_by(Expense.date.desc())
            .limit(10)
            .subquery()
        )
        result = await session.execute(select(func.avg(subq.c.amount)))
        avg = result.scalar()
        return float(avg) if avg is not None else None


async def _score_by_keyword_avg(
    telegram_id: int,
    candidates: list[tuple],
    current_amount: float,
) -> tuple | None:
    best_pair = None
    best_distance = float("inf")
    for cat, kw in candidates:
        avg = await _get_keyword_avg(telegram_id, kw, cat.id)
        if avg is not None:
            distance = abs(current_amount - avg)
            if distance < best_distance:
                best_distance = distance
                best_pair = (cat, kw)
    return best_pair


async def seed_user_categories(telegram_id: int):
    """Create or migrate default categories for a user."""
    if telegram_id in _seeded_users:
        return []

    async with async_session_maker() as session:
        result = await session.execute(select(Category).where(Category.telegram_id == telegram_id))
        existing = list(result.scalars().all())

        if existing:
            has_keywords = any(_parse_keywords(c.keywords) for c in existing)
            if has_keywords:
                _seeded_users.add(telegram_id)
                return existing
            # Old categories with empty keywords: update in-place
            name_to_new_keywords = {}
            for display_name, kw in DEFAULT_CATEGORIES.items():
                raw_name = " ".join(display_name.split()[1:])
                name_to_new_keywords[raw_name.lower()] = kw
            for cat in existing:
                kw = name_to_new_keywords.get(cat.name.lower(), [])
                cat.keywords = _dump_keywords(kw)
            await session.commit()
            _seeded_users.add(telegram_id)
            return existing

        categories = []
        for display_name, keywords in DEFAULT_CATEGORIES.items():
            raw_name = " ".join(display_name.split()[1:])
            cat = Category(
                telegram_id=telegram_id,
                name=raw_name,
                keywords=_dump_keywords(keywords),
            )
            session.add(cat)
            categories.append(cat)

        await session.commit()
        _seeded_users.add(telegram_id)
        return categories


async def get_user_categories(telegram_id: int) -> list[Category]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Category)
            .where(
                Category.telegram_id == telegram_id,
                Category.is_archived == False,
            )
            .order_by(Category.id)
        )
        return list(result.scalars().all())


async def get_all_categories(telegram_id: int) -> list[Category]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Category)
            .where(Category.telegram_id == telegram_id)
            .order_by(Category.is_archived, Category.id)
        )
        return list(result.scalars().all())


async def find_closest_category(
    user_input: str,
    telegram_id: int,
    current_amount: float = 0,
) -> tuple[Category | None, str]:
    """
    Find the closest matching category for user_input.
    Returns (category, matched_keyword).
    If no match found, returns the "Прочее" category.
    """
    target = clean_and_normalize(user_input)
    categories = await get_user_categories(telegram_id)

    if not categories:
        return None, target

    # 0. Autocorrect description against all known keywords
    all_keywords: set[str] = set()
    for cat in categories:
        for kw in _parse_keywords(cat.keywords):
            all_keywords.add(kw)

    corrected_target = _autocorrect_description(target, all_keywords)

    # 1. Exact keyword match — collect ALL candidates
    matched_candidates: list[tuple[Category, str]] = []
    for cat in categories:
        keywords = _parse_keywords(cat.keywords)
        for kw in keywords:
            if kw in corrected_target or corrected_target in kw:
                matched_candidates.append((cat, kw))
                break

    if len(matched_candidates) == 1:
        return matched_candidates[0]
    elif len(matched_candidates) > 1:
        if current_amount > 0:
            best = await _score_by_keyword_avg(telegram_id, matched_candidates, current_amount)
            if best:
                return best
        return matched_candidates[0]

    # 2. Typo protection: compare against category names
    cat_names = {cat.name: cat for cat in categories}
    closest = difflib.get_close_matches(
        user_input.capitalize(),
        list(cat_names.keys()),
        n=1,
        cutoff=0.6,
    )
    if closest:
        return cat_names[closest[0]], closest[0]

    # 3. Substring match in description parts
    words = corrected_target.split()
    for word in words:
        for cat in categories:
            keywords = _parse_keywords(cat.keywords)
            closest_word = difflib.get_close_matches(word, keywords, n=1, cutoff=0.7)
            if closest_word:
                return cat, closest_word[0]

    # 4. Fallback to "Прочее"
    for cat in categories:
        if cat.name == "Прочее":
            return cat, corrected_target

    return categories[-1], corrected_target


async def add_keyword_to_category(
    telegram_id: int,
    category_id: int,
    keyword: str,
):
    """Add a keyword to a category's keyword list (self-learning)."""
    word = clean_and_normalize(keyword)
    if not word:
        return

    async with async_session_maker() as session:
        result = await session.execute(
            select(Category).where(
                Category.id == category_id,
                Category.telegram_id == telegram_id,
            )
        )
        cat = result.scalar_one_or_none()
        if not cat:
            return

        keywords = _parse_keywords(cat.keywords)
        if word not in keywords:
            keywords.append(word)
            cat.keywords = _dump_keywords(keywords)
            await session.commit()


def get_category_display(category_name: str) -> tuple[str, str]:
    """Return (emoji, display_name) for a category name."""
    key = category_name.lower().strip()
    emoji = CATEGORY_EMOJI_MAP.get(key, "📦")
    display = CATEGORY_NAME_MAP.get(key, category_name)
    return emoji, display


async def detect_category_db(
    text: str,
    telegram_id: int,
    current_amount: float = 0,
) -> tuple[Category | None, str]:
    """Detect category from text using DB-backed categories.
    Returns (category, matched_keyword)."""
    return await find_closest_category(text, telegram_id, current_amount)
