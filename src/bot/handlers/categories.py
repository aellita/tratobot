from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from src.utils import phrases

from ...db.database import async_session_maker
from ...db.models.models import Category
from ...services.categorization import (
    get_all_categories,
    get_category_display,
)
from ...services.category_service import (
    get_category_expense_count,
    hard_delete_category,
    move_expenses_to_default_and_delete,
    rename_category,
    toggle_archive_category,
)
from ...utils.helpers import safe
from ..keyboards import get_main_menu_keyboard

router = Router()
PAGE_SIZE = 5

_cat_back_target: dict[int, str] = {}


def _set_back_target(user_id: int, callback_data: str):
    _cat_back_target[user_id] = callback_data


def _get_back_target(user_id: int) -> str | None:
    return _cat_back_target.get(user_id)


def _pop_back_target(user_id: int) -> str | None:
    return _cat_back_target.pop(user_id, None)


class CategoryRename(StatesGroup):
    waiting_for_name = State()


async def _build_list_keyboard(
    page: int, total_pages: int, page_items: list[Category], user_id: int = 0
) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    offset = page * PAGE_SIZE
    for i, cat in enumerate(page_items):
        row.append(
            InlineKeyboardButton(
                text=str(i + 1 + offset), callback_data=f"cat_sel:{cat.id}"
            )
        )
    if row:
        buttons.append(row)
    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text=phrases.BTN_HISTORY_BACK,
                callback_data=f"cat_page:{page - 1}",
            )
        )
    if page < total_pages - 1:
        nav.append(
            InlineKeyboardButton(
                text=phrases.BTN_HISTORY_FWD,
                callback_data=f"cat_page:{page + 1}",
            )
        )
    if page > 0 or page < total_pages - 1:
        buttons.append(nav)
    nav_buttons = []
    back_target = _get_back_target(user_id) if user_id else None
    if back_target:
        nav_buttons.append(
            InlineKeyboardButton(text=phrases.BTN_BACK, callback_data=back_target)
        )
    nav_buttons.append(
        InlineKeyboardButton(text=phrases.BTN_BACK_TO_MENU, callback_data="menu_back")
    )
    buttons.append(nav_buttons)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _render_category_page(telegram_id: int, page: int) -> tuple[str, InlineKeyboardMarkup]:
    all_cats = await get_all_categories(telegram_id)
    if not all_cats:
        return phrases.CATEGORY_LIST_EMPTY, await get_main_menu_keyboard(telegram_id)

    active = [c for c in all_cats if not c.is_archived]
    archived = [c for c in all_cats if c.is_archived]
    ordered = active + archived
    total_items = len(ordered)
    total_pages = max((total_items + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_items = ordered[start:end]

    lines = [phrases.CATEGORY_MANAGEMENT_TITLE.format(page=page + 1, total=total_pages)]
    active_start_idx = 0
    archived_start_idx = len(active)

    for i, cat in enumerate(page_items):
        global_idx = start + i
        emoji, _ = get_category_display(cat.name)

        if global_idx == active_start_idx and active:
            lines.append(phrases.CATEGORY_LIST_ACTIVE_HEADER)
        if global_idx == archived_start_idx and archived:
            lines.append(phrases.CATEGORY_LIST_ARCHIVED_HEADER)

        label = f"{emoji} {global_idx + 1}. {cat.name}"
        if cat.is_archived:
            label += phrases.CATEGORY_LIST_ARCHIVED_SUFFIX
        lines.append(label)

    text = "\n".join(lines)
    kb = await _build_list_keyboard(page, total_pages, page_items, telegram_id)
    return text, kb


@router.callback_query(F.data.startswith("menu_categories"))
async def cmd_categories(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    parts = callback.data.split(":")
    if len(parts) == 2:
        try:
            expense_id = int(parts[1])
            _set_back_target(callback.from_user.id, f"change_cat:{expense_id}")
        except (IndexError, ValueError, TypeError):
            pass
    text, kb = await _render_category_page(callback.from_user.id, 0)
    await callback.message.edit_text(text=text, reply_markup=kb)


@router.callback_query(F.data.startswith("cat_page:"))
async def category_page(callback: CallbackQuery):
    await callback.answer()
    try:
        page = int(callback.data.split(":")[1])
    except (IndexError, ValueError, TypeError):
        await callback.message.edit_text(
            text=phrases.ERR_INVALID_DATA,
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )
        return

    text, kb = await _render_category_page(callback.from_user.id, page)
    await callback.message.edit_text(text=text, reply_markup=kb)


@router.callback_query(F.data.startswith("cat_sel:"))
async def category_detail(callback: CallbackQuery):
    await callback.answer()
    try:
        category_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError, TypeError):
        await callback.message.edit_text(
            text=phrases.ERR_INVALID_DATA,
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )
        return

    async with async_session_maker() as session:
        result = await session.execute(
            select(Category).where(
                Category.id == category_id,
                Category.telegram_id == callback.from_user.id,
            )
        )
        cat = result.scalar_one_or_none()

    if not cat:
        await callback.message.edit_text(
            text=phrases.CATEGORY_NOT_FOUND,
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )
        return

    count = await get_category_expense_count(callback.from_user.id, category_id)
    emoji, _ = get_category_display(cat.name)

    text = phrases.CATEGORY_DETAIL_HEADER.format(emoji=emoji, name=safe(cat.name), count=count)
    if cat.is_archived:
        text += phrases.CATEGORY_DETAIL_ARCHIVED_NOTE

    buttons = [
        [
            InlineKeyboardButton(
                text=phrases.BTN_CATEGORY_RENAME, callback_data=f"cat_rename:{category_id}"
            )
        ],
    ]

    if cat.is_archived:
        buttons.append([
            InlineKeyboardButton(
                text=phrases.BTN_CATEGORY_UNARCHIVE, callback_data=f"cat_unarchive:{category_id}"
            )
        ])
    else:
        buttons.append([
            InlineKeyboardButton(
                text=phrases.BTN_CATEGORY_ARCHIVE, callback_data=f"cat_archive:{category_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text=phrases.BTN_CATEGORY_DELETE, callback_data=f"cat_delete:{category_id}"
        )
    ])
    buttons.append([
        InlineKeyboardButton(
            text=phrases.BTN_CATEGORY_BACK_TO_LIST, callback_data="cat_back"
        )
    ])

    await callback.message.edit_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("cat_rename:"))
async def category_rename_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        category_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError, TypeError):
        await callback.message.edit_text(
            text=phrases.ERR_INVALID_DATA,
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )
        return

    async with async_session_maker() as session:
        result = await session.execute(
            select(Category).where(
                Category.id == category_id,
                Category.telegram_id == callback.from_user.id,
            )
        )
        cat = result.scalar_one_or_none()

    if not cat:
        await callback.message.edit_text(
            text=phrases.CATEGORY_NOT_FOUND,
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )
        return

    await state.update_data(cat_rename_id=category_id)
    await state.set_state(CategoryRename.waiting_for_name)
    await callback.message.edit_text(
        text=phrases.CATEGORY_RENAME_PROMPT.format(name=safe(cat.name)),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=phrases.BTN_CANCEL, callback_data="cat_cancel_rename")],
            ]
        ),
    )


@router.callback_query(F.data == "cat_cancel_rename")
async def category_rename_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    text, kb = await _render_category_page(callback.from_user.id, 0)
    await callback.message.edit_text(text=text, reply_markup=kb)


@router.message(CategoryRename.waiting_for_name)
async def process_cat_rename(message: Message, state: FSMContext):
    raw = message.text.strip()
    if not raw or len(raw) > 30:
        await message.answer(phrases.ERR_NAME_LENGTH)
        return

    data = await state.get_data()
    category_id = data.get("cat_rename_id")
    if not category_id:
        await state.clear()
        return

    async with async_session_maker() as session:
        result = await session.execute(
            select(Category).where(
                Category.id == category_id,
                Category.telegram_id == message.from_user.id,
            )
        )
        cat = result.scalar_one_or_none()
        if not cat:
            await state.clear()
            await message.answer(phrases.CATEGORY_NOT_FOUND, reply_markup=await get_main_menu_keyboard(message.from_user.id))
            return

        old_emoji, _ = get_category_display(cat.name)
        if ord(raw[0]) > 0x1F000:
            user_emoji = raw[0]
            text_part = raw[1:].strip()
            emoji = user_emoji
        else:
            text_part = raw
            emoji = old_emoji
        if not text_part:
            await message.answer(phrases.ERR_NAME_LENGTH)
            return
        text_part = text_part[0].upper() + text_part[1:].lower()
        new_name = f"{emoji} {text_part}"

        dup = await session.execute(
            select(Category).where(
                Category.telegram_id == message.from_user.id,
                Category.name == new_name,
                Category.id != category_id,
            )
        )
        if dup.scalar_one_or_none():
            await message.answer(phrases.ERR_CATEGORY_EXISTS.format(name=safe(new_name)))
            return

    success = await rename_category(message.from_user.id, category_id, new_name)
    await state.clear()

    if not success:
        await message.answer(phrases.CATEGORY_NOT_FOUND)
        return

    await message.answer(
        text=phrases.CATEGORY_RENAMED.format(name=safe(new_name)),
        reply_markup=await get_main_menu_keyboard(message.from_user.id),
    )


@router.callback_query(F.data.startswith("cat_archive:"))
async def category_archive(callback: CallbackQuery):
    await callback.answer()
    try:
        category_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError, TypeError):
        return

    async with async_session_maker() as session:
        result = await session.execute(
            select(Category).where(
                Category.id == category_id,
                Category.telegram_id == callback.from_user.id,
            )
        )
        cat = result.scalar_one_or_none()

    if not cat:
        await callback.message.edit_text(
            text=phrases.CATEGORY_NOT_FOUND,
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )
        return

    await toggle_archive_category(callback.from_user.id, category_id)
    await callback.message.edit_text(
        text=phrases.CATEGORY_ARCHIVED.format(name=safe(cat.name)),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text=phrases.BTN_CATEGORY_BACK_TO_LIST,
                    callback_data="cat_back",
                )],
            ]
        ),
    )


@router.callback_query(F.data.startswith("cat_unarchive:"))
async def category_unarchive(callback: CallbackQuery):
    await callback.answer()
    try:
        category_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError, TypeError):
        return

    async with async_session_maker() as session:
        result = await session.execute(
            select(Category).where(
                Category.id == category_id,
                Category.telegram_id == callback.from_user.id,
            )
        )
        cat = result.scalar_one_or_none()

    if not cat:
        await callback.message.edit_text(
            text=phrases.CATEGORY_NOT_FOUND,
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )
        return

    await toggle_archive_category(callback.from_user.id, category_id)
    await callback.message.edit_text(
        text=phrases.CATEGORY_UNARCHIVED.format(name=safe(cat.name)),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text=phrases.BTN_CATEGORY_BACK_TO_LIST,
                    callback_data="cat_back",
                )],
            ]
        ),
    )


@router.callback_query(F.data.startswith("cat_delete:"))
async def category_delete_warning(callback: CallbackQuery):
    await callback.answer()
    try:
        category_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError, TypeError):
        return

    async with async_session_maker() as session:
        result = await session.execute(
            select(Category).where(
                Category.id == category_id,
                Category.telegram_id == callback.from_user.id,
            )
        )
        cat = result.scalar_one_or_none()

    if not cat:
        await callback.message.edit_text(
            text=phrases.CATEGORY_NOT_FOUND,
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )
        return

    count = await get_category_expense_count(callback.from_user.id, category_id)

    buttons = [
        [
            InlineKeyboardButton(
                text=phrases.BTN_CATEGORY_DELETE_ARCHIVE,
                callback_data=f"cat_archive:{category_id}",
            )
        ],
        [
            InlineKeyboardButton(
                text=phrases.BTN_CATEGORY_DELETE_MOVE,
                callback_data=f"cat_delete_move:{category_id}",
            )
        ],
        [
            InlineKeyboardButton(
                text=phrases.BTN_CATEGORY_DELETE_HARD,
                callback_data=f"cat_delete_hard:{category_id}",
            )
        ],
        [
            InlineKeyboardButton(
                text=phrases.BTN_BACK,
                callback_data="cat_back",
            )
        ],
    ]

    await callback.message.edit_text(
        text=phrases.CATEGORY_DELETE_WARNING.format(name=safe(cat.name), count=count),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("cat_delete_move:"))
async def category_delete_move(callback: CallbackQuery):
    await callback.answer()
    try:
        category_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError, TypeError):
        return

    async with async_session_maker() as session:
        result = await session.execute(
            select(Category).where(
                Category.id == category_id,
                Category.telegram_id == callback.from_user.id,
            )
        )
        cat = result.scalar_one_or_none()

    if not cat:
        await callback.message.edit_text(
            text=phrases.CATEGORY_NOT_FOUND,
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )
        return

    name = cat.name
    success = await move_expenses_to_default_and_delete(callback.from_user.id, category_id)

    if not success:
        await callback.message.edit_text(
            text=phrases.CATEGORY_NOT_FOUND,
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )
        return

    await callback.message.edit_text(
        text=phrases.CATEGORY_DELETED_MOVED.format(name=safe(name)),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text=phrases.BTN_CATEGORY_BACK_TO_LIST,
                    callback_data="cat_back",
                )],
            ]
        ),
    )


@router.callback_query(F.data.startswith("cat_delete_hard:"))
async def category_delete_hard_confirm(callback: CallbackQuery):
    await callback.answer()
    try:
        category_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError, TypeError):
        return

    async with async_session_maker() as session:
        result = await session.execute(
            select(Category).where(
                Category.id == category_id,
                Category.telegram_id == callback.from_user.id,
            )
        )
        cat = result.scalar_one_or_none()

    if not cat:
        await callback.message.edit_text(
            text=phrases.CATEGORY_NOT_FOUND,
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )
        return

    await callback.message.edit_text(
        text=phrases.CATEGORY_DELETE_CONFIRM_PROMPT,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=phrases.BTN_CATEGORY_BACK_TO_LIST,
                        callback_data="cat_back",
                    ),
                    InlineKeyboardButton(
                        text=phrases.BTN_CATEGORY_DELETE_CONFIRM,
                        callback_data=f"cat_delete_confirm:{category_id}",
                    ),
                ],
            ]
        ),
    )


@router.callback_query(F.data.startswith("cat_delete_confirm:"))
async def category_delete_hard_execute(callback: CallbackQuery):
    await callback.answer()
    try:
        category_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError, TypeError):
        return

    async with async_session_maker() as session:
        result = await session.execute(
            select(Category).where(
                Category.id == category_id,
                Category.telegram_id == callback.from_user.id,
            )
        )
        cat = result.scalar_one_or_none()

    if not cat:
        await callback.message.edit_text(
            text=phrases.CATEGORY_NOT_FOUND,
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )
        return

    name = cat.name
    success = await hard_delete_category(callback.from_user.id, category_id)

    if not success:
        await callback.message.edit_text(
            text=phrases.CATEGORY_NOT_FOUND,
            reply_markup=await get_main_menu_keyboard(callback.from_user.id),
        )
        return

    await callback.message.edit_text(
        text=phrases.CATEGORY_DELETED_HARD.format(name=safe(name)),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text=phrases.BTN_CATEGORY_BACK_TO_LIST,
                    callback_data="cat_back",
                )],
            ]
        ),
    )


@router.callback_query(F.data == "cat_back")
async def category_back_to_list(callback: CallbackQuery):
    await callback.answer()
    text, kb = await _render_category_page(callback.from_user.id, 0)
    await callback.message.edit_text(text=text, reply_markup=kb)
