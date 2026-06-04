# progress.md — Журнал сессий и решений

> Сюда записываются ключевые решения, отклонённые подходы, открытые вопросы и заметки, влияющие на разработку. Не дублирует PRD и README.

---

## Когда писать

- ✅ Принято архитектурное решение (почему выбрали X, а не Y)
- ❌ Попробовали подход, но отказались (почему не подошёл)
- ❓ Открытый вопрос, который нужно решить в будущем
- 🧠 Инсайт или наблюдение, важное для следующих сессий
- 📌 Договорённость с пользователем о нейминге, стиле, подходах

---

## Формат записи

```
### YYYY-MM-DD — краткая тема сессии

- **Решение:** ... (почему)
- **Отклонено:** ... (причина)
- **Открыто:** ...
- **Заметки:** ...
```

---

## Записи

### 2026-06-03 — Security audit + создание PRD/RULES/progress/README

- **Решение:** Созданы PRD.md, RULES.md, progress.md, обновлён README.md с Implementation Status
- **Решение:** Стиль бота — ироничный напарник, «бро» разрешён
- **Решение:** SQLAlchemy оставлена как ORM (не мигрировать на raw SQL)
- **Решение:** Railway как основной хостинг ($5/мес), VPS не нужен
- **🧠 Аудит безопасности:** найдено 19 уязвимостей (3 High, 9 Medium, 7 Low). Все исправлены.

### 2026-06-03 — Security fix session (Block 1-3)

- **Сделано:** Все 19 findings закрыты
  - H1: `.env` удалён
  - H2: `parse_amount()` — валидация inf/nan/negative/1e12
  - H3: Миграции — allow-list + params
  - M1: Проверка владельца категории
  - M2: Callback data — try/except в 10 местах
  - M3: RateLimitMiddleware (0.7s, burst 5/3s)
  - M4: `safe(html.escape())` — 4 файла
  - M5: ✅ покрыто H2
  - M6: Автовыход из FSM после 3 ошибок
  - M7: Финансы убраны из логов
  - M8: bare `except:` → `except (ValueError, TypeError)`
  - M9: Лимиты длины (description 500, wishlist_name 255)
  - L1: extra="allow" → ✅ исправлено (config.py)
  - L2: _last_keyboard растёт бесконечно — нужен TTLCache или document
  - L3: setattr без allow-list → ✅ исправлено (budget_service.py)
  - L4: datetime.utcnow() deprecated — заменить на datetime.now(timezone.utc) во всех файлах (models.py, menu.py, expense_service.py, budget_service.py, goal_service.py, evening_report.py, morning_report.py)
  - L5: unused import func → ✅ исправлено (keyboards.py)
  - L6: seed_user_categories вызывается при каждой трате → кеширование или флаг
  - L7: parse_expense_text суммирует все числа ("500 кофе 300 пирожок" = 800) — брать первое число
- **Создано:** `src/utils/helpers.py`, `src/bot/middleware.py`
- **Открыто:** L4 (utcnow), L2 (_last_keyboard), L6 (seed_user_categories), L7 (parse_expense_text)

### План ремедиации (приоритеты)

#### Блок 1 (текущая сессия)
- [x] H1 — `.env` удалён, `.env.example` создан. Credentials только в Railway Variables
- [x] H2 — `float()` → `parse_amount()` с `math.isfinite()` + `0 < amount < 1e12` (12 мест в menu.py + history.py)
- [x] M4 — HTML injection → `safe(html.escape())` обёртка для description, wishlist_name (history.py, menu.py, evening_flow.py, evening_report.py)
- [x] M8 — Барe `except:` → `except (ValueError, TypeError)` (menu.py + expense_service.py)

#### Блок 2 (следующая сессия)
- [x] M1 — Проверка владельца категории при смене (menu.py:1049-1053)
- [x] M5 — ✅ Уже исправлено через H2 (parse_amount rejects negative)
- [x] M2 — Валидация callback data (history.py 5 мест + menu.py: change_cat, set_cat, new_cat, fix_overdraft)
- [x] M8 — ✅ Уже исправлено в Блоке 1

#### Блок 3 (ближайшие сессии)
- [x] M3 — Rate limiting middleware (0.7s между запросами, макс 5 за 3с)
- [x] M6 — Автовыход из FSM после 3 неудачных попыток (process_expense, process_period_start, save_edit_expense)
- [x] H3 — Миграции: валидация идентификаторов через allow-list + параметризованные запросы в information_schema
- [x] M7 — Убраны финданные из логов (morning_report.py — pct_pred/pct_sim/spent)
- [x] M9 — Лимиты длины: clean_description → 500, wishlist_name → 255
- [ ] L1-L7 — Низкоприоритетные

#### Низкоприоритетные (L)
- [x] L1 — `extra="allow"` → убрано из config.py
- [x] L2 — `_last_keyboard` утечка памяти (menu.py:79) → TTLCache (maxsize=1024, ttl=3600)
- [x] L3 — `setattr` без allow-list → ALLOWED_FIELDS добавлен
- [x] L4 — `datetime.utcnow()` → уже отсутствует в коде (использовать `datetime.now(timezone.utc)`)
- [x] L5 — unused import `func` → удалён из keyboards.py
- [x] L6 — `seed_user_categories` → уже кешируется через `_seeded_users` set
- [x] L7 — `parse_expense_text` → уже берёт первое число (break после первого amount > 0)

### 2026-06-03 — L-task cleanup + tests prep
- **Сделано:** Все L-задачи закрыты
- **Сделано:** L2 — `_last_keyboard` заменён на `TTLCache` из `cachetools` (добавлен в requirements.txt)
- **Проверено:** L4/L6/L7 уже были исправлены в коде, обновлён статус в progress.md

### 2026-06-03 — Тесты: Очередь 1 (чистые функции) + BigTech Standard

**Bug-трекинг завершён.** Все security-фиксы (19/19) и L-задачи (7/7) закрыты.

**Сделано:**
- `pytest` + `pytest-asyncio` в requirements.txt
- 133 теста в 3 файлах (Очередь 1)
- BigTech Standard закреплён в RULES.md раздел 6 (9 категорий сценариев)
- Каждый модуль покрыт: happy path, empty/null, boundary, overflow, special chars, locale, type/cast, negative/edge

**Файлы:**
- `tests/test_expense_parser.py` — `parse_expense_text`, `parse_multi_expense_text`, `clean_description`
- `tests/test_helpers.py` — `parse_amount`, `safe`, `parse_callback`, `extract_callback_id`
- `tests/test_categorization.py` — `clean_and_normalize`, `get_category_display`, `_parse_keywords`, `_dump_keywords`

---

### 2026-06-04 — Тесты: Очередь 2 (с моками БД)

**Сделано:**
- `tests/conftest.py` — in-memory SQLite engine, `async_session_maker` monkeypatch, фикстуры (test_user, test_budget, test_goal, test_expense, test_settings)
- `tests/test_budget_service.py` — 21 тест: `get_active_budget` (7), `reconcile_budget_with_reality` (7), `update_budget_field` (7)
- `tests/test_goal_service.py` — 18 тестов: `add_spare_change_to_goal` (8), `deduct_from_goal` (10)
- `tests/test_expense_service_db.py` — 20 тестов: `try_apply_round_up` (10), `get_current_period_expenses_sum` (10)
- Итого: 59 новых тестов (всего 192)
- Продакшен-код не менялся — багов не найдено

**Отклонено:** `get_today_expenses_sum` — не вошёл в запрос, сделан только по ТЗ

---

### 2026-06-04 — Queue 3: FSM/integration tests + ruff fix + pre-commit + CI

**Сделано:**
- `tests/test_onboarding_fsm.py` — 33 теста: `_parse_wishlist` (9), `process_income` (4), `process_period_start` (5), `process_mandatory` (3), `process_black_day` (3), `process_wishlist_name` (2), `skip_step` (5), `handle_rounding_choice` (3), `handle_period_start_choice` (4)
- `tests/test_critical_reset.py` — 15 тестов: `trigger_critical_reset` (1), `save_real_balance` green/yellow/red zone (5), `fresh_start_save_mandatory` (3), `fresh_start_save_black_day` (3), `fresh_start_save_balance` (3)
- `tests/test_history_edit.py` — 10 тестов: `save_edit_expense` (7), `start_edit_expense` (3)
- `tests/test_expense_service_db.py` — расширен `soft_delete_expense` (4), `restore_expense` (4), `update_expense_amount` (5) — 13 новых тестов
- Итого: 77 новых тестов (всего 269)
- `conftest.py` — добавлен `keyboards.py` в `_patch_session_maker` (хендлеры вызывают `get_main_menu_keyboard`, которая уходила в реальную БД)

**Ruff auto-fix incident:**
- Применила `ruff check --fix --unsafe-fixes`, который заменил `Expense.is_deleted == False` на `not Expense.is_deleted` в SQLAlchemy WHERE-выражениях. В SQLAlchemy `not` над Column выбрасывает `ValueError`.
- **Решение:** откатила unsafe-изменения в 4 файлах (expense_service.py, goal_service.py, menu.py, history.py), применила только безопасные фиксы (import sorting, f-string, UP017, whitespace).
- **Вывод:** `--unsafe-fixes` для E712 нельзя применять к коду с SQLAlchemy.

**pre-commit + CI:**
- `.pre-commit-config.yaml` — ruff (lint+format), mypy, pytest, базовые хуки
- `.github/workflows/test.yml` — GitHub Actions (ruff check + format, mypy, pytest)
- `pyproject.toml` — конфиг ruff (line-length=100), mypy
- `requirements-dev.txt` — ruff, mypy, pre-commit

**Предстоит:**
- `phrases.py` — вынос строк из хендлеров
- Пуш на GitHub (ожидает команды пользователя)

---

## Шпаргалка для агента

После каждой сессии (или по запросу пользователя) агент проверяет: было ли что-то из списка «Когда писать». Если да — добавляет запись в этот файл перед завершением работы.
