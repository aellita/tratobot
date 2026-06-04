import difflib
import json

from sqlalchemy import select

from ..db.database import async_session_maker
from ..db.models.models import Category

_seeded_users: set[int] = set()


GREETINGS = [
    "Наконец-то ты пришел! Давай сделаем так, чтобы твои деньги перестали испаряться",
    "Наконец-то мы встретились! Я уже подготовил всё для нашего финансового прорыва. Обещаю быть полезным и не слишком занудным",
    "Привет! Я очень ждал твоего появления. Давай наведем порядок в кошельке так, чтобы на всё хватало и еще оставалось",
]

DEFAULT_CATEGORIES = {
    "🍔 Еда": ["еда", "продукты", "супермаркет", "пятерочка", "магнит", "ашан", "вкусвилл", "обед", "ужин", "завтрак", "кофе", "чай", "пицца", "суши", "шаурма", "бургер", "макдоналдс"],
    "🚌 Транспорт": ["такси", "метро", "автобус", "бензин", "заправка", "парковка", "самокат", "электричка"],
    "🍽 Кафе": ["кафе", "ресторан", "бургер", "кофе", "пицца", "суши", "шаурма", "макдоналдс", "бар", "кофейня"],
    "💊 Здоровье": ["аптека", "врач", "лекарства", "стоматолог", "анализы", "клиника", "больница"],
    "🎮 Развлечения": ["кино", "театр", "концерт", "бар", "клуб", "игра", "музей", "steam", "netflix"],
    "🛒 Покупки": ["одежда", "обувь", "вайлдберриз", "озон", "куртка", "кроссовки", "доставка", "косметика"],
    "🏠 Дом": ["аренда", "коммуналка", "свет", "интернет", "ремонт", "мебель", "жкх"],
    "💇 Красота": ["стрижка", "барбер", "салон", "косметика", "маникюр"],
    "🏋️ Спорт": ["зал", "фитнес", "бассейн", "тренер", "спорттовары"],
    "📱 Подписки": ["подписка", "netflix", "spotify", "youtube", "apple", "google"],
    "📦 Прочее": [],
}

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


async def seed_user_categories(telegram_id: int):
    """Create or migrate default categories for a user."""
    if telegram_id in _seeded_users:
        return []

    async with async_session_maker() as session:
        result = await session.execute(
            select(Category).where(Category.telegram_id == telegram_id)
        )
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
            select(Category).where(Category.telegram_id == telegram_id)
        )
        return list(result.scalars().all())


async def find_closest_category(
    user_input: str,
    telegram_id: int,
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

    # 1. Exact keyword match
    for cat in categories:
        keywords = _parse_keywords(cat.keywords)
        for kw in keywords:
            if kw in target or target in kw:
                return cat, kw

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
    words = target.split()
    for word in words:
        for cat in categories:
            keywords = _parse_keywords(cat.keywords)
            closest_word = difflib.get_close_matches(word, keywords, n=1, cutoff=0.7)
            if closest_word:
                return cat, closest_word[0]

    # 4. Fallback to "Прочее"
    for cat in categories:
        if cat.name == "Прочее":
            return cat, target

    return categories[-1], target


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


async def detect_category_db(text: str, telegram_id: int) -> tuple[Category | None, str]:
    """
    Detect category from text using DB-backed categories.
    Returns (category, matched_keyword).
    Seeds / migrates categories for the user if needed.
    """
    await seed_user_categories(telegram_id)
    return await find_closest_category(text, telegram_id)
