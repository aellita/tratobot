# TratoBot — Telegram-бот учёта финансов

Python 3.12 · aiogram 3.x · SQLAlchemy 2.0 async · PostgreSQL (prod) / SQLite (dev) · Railway.

## Начало сессии

1. Прочти `agent/RULES.md` — workflow сессии и запреты.
2. Прочти `agent/progress.md` — статус, что сделано, инварианты.
3. Прочти `agent/SESSION_PLAN.md` — порядок задач; для текущего аудита — `agent/bugs_2026-11-06.md`.
4. Для продуктовых сверок — `agent/PRD.md`, витрина — `README.md`.

## Границы

Работаем **только внутри** `/Users/aelita-lu/Tratobot/tratobot`. Не читаем и не пишем выше по дереву (`~/...`, `~/.opencode`, соседние папки) без явного разрешения пользователя.

## Команды

```bash
pytest -q                       # 813 тестов, in-memory SQLite
python -m src.db.schema_audit   # сверка моделей с реальной БД (read-only, exit 1 critical / 2 read error)
ruff check --select F .         # линтер
```

## Инварианты (детали — в progress.md)

- `get_money_for_life` / `get_period_spent` / `get_daily_pred` — единственный канон остатка.
- `apply_reconciliation` пишет `free_money + spent_at_recalc` атомарно.
- `save_budget` на UPDATE не трогает `spent_at_recalc`.
- Без `@review` диффа — не пушить.

## Доки агента

Все рабочие `.md` — в `agent/` (PRD, RULES, progress, SESSION_PLAN, bugs_ux4, bugs_2026-11-06).
