from datetime import datetime

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select

from ...db.database import async_session_maker
from ...db.models.models import User, Expense
from ...services.expense_service import (
    get_expense_page,
    soft_delete_expense,
    restore_expense,
    update_expense_amount,
)
from ...services.categorization import CATEGORIES, detect_category
from ..keyboards import get_cancel_keyboard, get_main_menu_keyboard

router = Router()


class EditExpense(StatesGroup):
    waiting_for_amount = State()


PAGE_SIZE = 5
CAT_EMOJI = {v.split()[0] for v in CATEGORIES.values()}


def _expense_line(idx: int, exp: Expense) -> str:
    cat_name = detect_category(exp.description or "")
    emoji = CATEGORIES.get(cat_name, "📦").split()[0]
    date_str = exp.date.strftime("%d %b").lower()
    desc = exp.description or cat_name
    return f"{idx}. {emoji} {exp.amount:,.0f}₽ — {desc} ({date_str})"


def _build_list_keyboard(expenses: list[Expense], page: int, total_pages: int):
    buttons = []
    row = []
    for i, exp in enumerate(expenses):
        row.append(InlineKeyboardButton(
            text=str(i + 1),
            callback_data=f"exp_sel:{exp.id}"
        ))
    if row:
        buttons.append(row)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"exp_page:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="Вперед ▶️", callback_data=f"exp_page:{page + 1}"))

    # Only show nav row if there's something to navigate
    if page > 0 or page < total_pages - 1:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="menu_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _build_detail_keyboard(expense_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Изменить сумму", callback_data=f"exp_edit:{expense_id}"),
            InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"exp_del:{expense_id}"),
        ],
        [InlineKeyboardButton(text="🔙 Назад к списку", callback_data="exp_back")],
    ])


def _build_deleted_keyboard(expense_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Восстановить", callback_data=f"exp_undo:{expense_id}")],
        [InlineKeyboardButton(text="🔙 Назад к списку", callback_data="exp_back")],
    ])


async def _get_user_id(telegram_id: int) -> int | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        return user.id if user else None


# ============ HISTORY LIST ============

@router.callback_query(F.data == "menu_history")
async def cmd_history(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()

    expenses, total, total_pages = await get_expense_page(callback.from_user.id, 0)

    if total == 0:
        await callback.message.edit_text(
            text="📜 <b>История трат</b>\n\n"
                 "У тебя пока нет записанных трат.\n"
                 "Нажми «💸 Добавить трату», чтобы начать!",
            reply_markup=await get_main_menu_keyboard(callback.from_user.id)
        )
        return

    lines = [_expense_line(i + 1, exp) for i, exp in enumerate(expenses)]
    text = (f"📜 <b>История трат (стр. {1}/{total_pages}):</b>\n\n"
            + "\n".join(lines))

    await callback.message.edit_text(
        text=text,
        reply_markup=_build_list_keyboard(expenses, 0, total_pages)
    )


# ============ PAGINATION ============

@router.callback_query(F.data.startswith("exp_page:"))
async def history_page(callback: CallbackQuery):
    await callback.answer()
    page = int(callback.data.split(":")[1])

    expenses, total, total_pages = await get_expense_page(callback.from_user.id, page)

    lines = [_expense_line(i + 1 + page * PAGE_SIZE, exp) for i, exp in enumerate(expenses)]
    text = (f"📜 <b>История трат (стр. {page + 1}/{total_pages}):</b>\n\n"
            + "\n".join(lines))

    await callback.message.edit_text(
        text=text,
        reply_markup=_build_list_keyboard(expenses, page, total_pages)
    )


# ============ EXPENSE DETAIL ============

@router.callback_query(F.data.startswith("exp_sel:"))
async def expense_detail(callback: CallbackQuery):
    await callback.answer()
    expense_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        user = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = user.scalar_one_or_none()
        if not user:
            return

        result = await session.execute(
            select(Expense).where(
                Expense.id == expense_id,
                Expense.user_id == user.id,
                Expense.is_deleted == False
            )
        )
        expense = result.scalar_one_or_none()

    if not expense:
        await callback.message.edit_text(
            text="❌ Трата не найдена или уже удалена.",
            reply_markup=await get_main_menu_keyboard(callback.from_user.id)
        )
        return

    category = detect_category(expense.description or "")
    emoji = CATEGORIES.get(category, "📦").split()[0]
    date_str = expense.date.strftime("%d %B %Y").lower()

    text = (f"⚙️ <b>Управление транзакцией:</b>\n\n"
            f"{emoji} <b>{category.capitalize()}</b>\n"
            f"💰 <b>Сумма:</b> {expense.amount:,.0f}₽\n"
            f"📝 <b>Описание:</b> {expense.description or '—'}\n"
            f"📅 <b>Дата:</b> {date_str}")

    await callback.message.edit_text(
        text=text,
        reply_markup=_build_detail_keyboard(expense.id)
    )


# ============ DELETE ============

@router.callback_query(F.data.startswith("exp_del:"))
async def delete_expense(callback: CallbackQuery):
    await callback.answer()
    expense_id = int(callback.data.split(":")[1])

    expense = await soft_delete_expense(callback.from_user.id, expense_id)

    if not expense:
        await callback.message.edit_text(
            text="❌ Не удалось удалить трату. Она уже удалена или не найдена.",
            reply_markup=await get_main_menu_keyboard(callback.from_user.id)
        )
        return

    await callback.message.edit_text(
        text=f"🗑️ <b>Трата удалена</b>\n\n"
             f"💰 {expense.amount:,.0f}₽ — {expense.description or 'трата'}\n\n"
             f"Если ошиблись — нажмите «Восстановить»",
        reply_markup=_build_deleted_keyboard(expense.id)
    )


# ============ UNDO DELETE ============

@router.callback_query(F.data.startswith("exp_undo:"))
async def undo_delete(callback: CallbackQuery):
    await callback.answer()
    expense_id = int(callback.data.split(":")[1])

    expense = await restore_expense(callback.from_user.id, expense_id)

    if not expense:
        await callback.message.edit_text(
            text="❌ Не удалось восстановить трату.",
            reply_markup=await get_main_menu_keyboard(callback.from_user.id)
        )
        return

    await callback.message.edit_text(
        text=f"✅ <b>Трата восстановлена!</b>\n\n"
             f"💰 {expense.amount:,.0f}₽ — {expense.description or 'трата'}",
        reply_markup=_build_detail_keyboard(expense.id)
    )


# ============ EDIT AMOUNT (FSM) ============

@router.callback_query(F.data.startswith("exp_edit:"))
async def start_edit_expense(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    expense_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        user = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = user.scalar_one_or_none()
        if not user:
            return

        result = await session.execute(
            select(Expense).where(
                Expense.id == expense_id,
                Expense.user_id == user.id,
                Expense.is_deleted == False
            )
        )
        expense = result.scalar_one_or_none()

    if not expense:
        await callback.message.edit_text(
            text="❌ Трата не найдена.",
            reply_markup=await get_main_menu_keyboard(callback.from_user.id)
        )
        return

    await state.update_data(edit_expense_id=expense.id)
    await state.set_state(EditExpense.waiting_for_amount)

    try:
        await callback.message.edit_text(
            text=f"✏️ Введи новую сумму для траты:\n\n"
                 f"💰 Текущая сумма: {expense.amount:,.0f}₽\n"
                 f"📝 {expense.description or 'трата'}",
            reply_markup=get_cancel_keyboard()
        )
    except TelegramBadRequest:
        await callback.message.delete()
        await callback.message.answer(
            text=f"✏️ Введи новую сумму для траты:\n\n"
                 f"💰 Текущая сумма: {expense.amount:,.0f}₽\n"
                 f"📝 {expense.description or 'трата'}",
            reply_markup=get_cancel_keyboard()
        )


@router.message(EditExpense.waiting_for_amount)
async def save_edit_expense(message: Message, state: FSMContext):
    data = await state.get_data()
    expense_id = data.get("edit_expense_id")

    if not expense_id:
        await state.clear()
        return

    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи число. Например: 500")
        return

    expense = await update_expense_amount(message.from_user.id, expense_id, amount)

    if not expense:
        await message.answer("❌ Трата не найдена.")
        await state.clear()
        return

    await state.clear()

    await message.answer(
        text=f"✅ <b>Сумма обновлена!</b>\n\n"
             f"💰 Новая сумма: {expense.amount:,.0f}₽\n"
             f"📝 {expense.description or 'трата'}",
        reply_markup=await get_main_menu_keyboard(message.from_user.id)
    )


# ============ BACK TO LIST ============

@router.callback_query(F.data == "exp_back")
async def back_to_list(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()

    expenses, total, total_pages = await get_expense_page(callback.from_user.id, 0)

    if total == 0:
        await callback.message.edit_text(
            text="📜 <b>История трат</b>\n\n"
                 "Список пуст.",
            reply_markup=await get_main_menu_keyboard(callback.from_user.id)
        )
        return

    lines = [_expense_line(i + 1, exp) for i, exp in enumerate(expenses)]
    text = (f"📜 <b>История трат (стр. {1}/{total_pages}):</b>\n\n"
            + "\n".join(lines))

    await callback.message.edit_text(
        text=text,
        reply_markup=_build_list_keyboard(expenses, 0, total_pages)
    )
