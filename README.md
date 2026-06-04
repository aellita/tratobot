# TratoBot — Бот для учёта финансов «Завтра на диете»

Telegram-бот для учёта личных финансов. Ироничный напарник, который помогает следить за бюджетом, копить на цели и не терять каркас.

---

## Implementation Status

### Completed

- **Онбординг и пользователи:** создание пользователя при первом запуске, пошаговая настройка бюджета (доход, период, обязательные, кубышка, хотелка, округление)
- **Бюджет:** создание/редактирование, дополнительный доход, смена дня старта периода, сброс бюджета
- **Расходы:** свободный текстовый ввод (одна строка и мультилайн), автокатегоризация по ключевым словам (difflib + self-learning), смена категории, создание своих категорий
- **История:** пагинация (по 5), мягкое удаление, восстановление, редактирование суммы, смена категории из детали
- **Статус:** зоны (зелёная/синяя/жёлтая/красная), дневной лимит, прогноз, симуляция кубышки
- **Хотелка:** автоокругление трат (10/100₽) с перечислением излишка, пополнение/списание
- **Кубышка:** резерв на чёрный день, кнопка «использовать кубышку» из статуса
- **Critical Reset:** 3-zone reconciliation (зелёная/жёлтая/красная), fresh-start ре-онбординг
- **Утренний отчёт (08:00 MSK):** автоматическая рассылка с зоной и клавиатурой
- **Вечерний teaser (22:00 MSK):** предложение добавить расходы, FSM-сбор контейнера
- **Автозакрытие (23:30 MSK):** финальный отчёт за день
- **Базы данных:** SQLite (dev), PostgreSQL (prod), schema-миграции (колонки, типы, ключи)
- **Деплой:** Docker, Railway.app, кросс-платформенная миграция БД
- **Команды разработчика:** `/test_evening`, `/test_teaser`, `/test_morning`

### Completed

- [x] **pre-commit hooks:** ruff (lint+format), mypy, pytest, базовые хуки (`trailing-whitespace`, `end-of-file-fixer`, `check-yaml`)
- [x] **GitHub Actions CI:** автоматический прогон ruff (check + format), mypy, pytest при push/PR на main
- [x] **Юнит-тесты:** 269 тестов — чистые функции (133), DB-mocked сервисы (59), FSM/integration (77)
- [x] **phrases.py:** все пользовательские строки вынесены в `src/utils/phrases.py` (8 файлов, ~180 замен)

### Remaining

- [ ] **Проверить production** — Railway авто-деплой и фикс таймзоны
- [ ] **Добить E501** — 135 ошибок (статусные footer'ы, YELLOW_SIM_*/RED_* зоны)
- [ ] **Голосовые сообщения:** парсинг через ASR + AI (заглушка готова)
- [ ] **Умные итоги месяца:** AI-генерация сводки с инсайтами
- [ ] **Режим отпуска:** смена валюты, отключение ворчания на рестораны
- [ ] **Аналитика выходные vs будни:** паттерны трат
- [ ] **AI-ассистент:** бот анализирует и подмечает, без прямого диалога с LLM
- [ ] **Рекламная интеграция (Shorts):** для будущей публичной версии

---

## Быстрый старт

```bash
pip install -r requirements.txt
python -m src.bot.main
```

## Деплой на Railway

1. Создай проект на railway.app
2. Подключи GitHub репозиторий
3. Добавь `BOT_TOKEN` и `DATABASE_URL` в переменные окружения
4. Задеплой

## Структура проекта

```
tratobot/
├── src/
│   ├── bot/
│   │   ├── handlers/   # menu.py, history.py, evening_flow.py, test_commands.py
│   │   ├── keyboards.py
│   │   ├── middleware.py
│   │   ├── scheduler.py
│   │   └── main.py
│   ├── services/        # budget, expense, goal, categorization, morning/evening report, user
│   ├── db/
│   │   ├── models/
│   │   └── database.py
│   ├── utils/           # helpers.py, phrases.py
│   └── core/
│       └── config.py
├── tests/               # 269 тестов (+ phrases.py regression check)
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
