# TratoBot — Бот для учёта финансов. 

Telegram-бот для учёта личных финансов. Ироничный напарник мужского пола, который помогает следить за бюджетом, копить на цели и не терять каркас.

---


## Структура проекта

```
tratobot/
├── src/
│   ├── bot/
│   │   ├── handlers/   # menu.py, history.py, categories.py, evening_flow.py, test_commands.py
│   │   ├── keyboards.py
│   │   ├── middleware.py
│   │   ├── scheduler.py
│   │   └── main.py
│   ├── services/        # budget, expense, goal, categorization, category, morning/evening report, user
│   ├── db/
│   │   ├── models/
│   │   └── database.py
│   ├── utils/           # helpers.py, phrases.py
│   └── core/
│       └── config.py
├── tests/               # 342 теста (+ phrases.py regression check)
│   ├── conftest.py
│   ├── test_budget_service.py
│   ├── test_categorization.py
│   ├── test_critical_reset.py
│   ├── test_expense_parser.py
│   ├── test_expense_service_db.py
│   ├── test_goal_service.py
│   ├── test_helpers.py
│   ├── test_history_edit.py
│   └── test_onboarding_fsm.py
├── .github/workflows/   # CI (GitHub Actions)
├── .pre-commit-config.yaml
├── Dockerfile
├── railway.json
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── PRD.md
├── RULES.md
└── progress.md
```

## Документация

| Файл | О чём |
|------|-------|
| `PRD.md` | Продуктовая спецификация |
| `RULES.md` | Правила разработки (для ИИ-агента) |
| `progress.md` | Журнал сессий и решений |
