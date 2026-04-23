# Обработчики команд бота
from .start import router as start_router
from .add_expense import router as add_expense_router

router = start_router
router.include_router(add_expense_router)