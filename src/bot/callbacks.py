from aiogram.filters.callback_data import CallbackData


class RolloverCb(CallbackData, prefix="rollover"):
    action: str
    budget_id: int
