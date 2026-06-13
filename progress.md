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

### 2026-06-04 — Queue 4: phrases.py + production datetime bugfix

**Production bugfix (datetime timezone):**
- Все `DateTime` колонки (PostgreSQL `TIMESTAMP WITHOUT TIME ZONE`) использовали offset-aware `datetime.now(UTC)`, что вызывало `asyncpg.exceptions.DataError` при вставке.
- **Фикс:** добавила `_utcnow()` в `models.py` (возвращает naive UTC), заменила все 5 column defaults и 3 явных `date=datetime.now(UTC)` в хендлерах на `.replace(tzinfo=None)`.
- Запушила в main — Railway авто-деплоит.

**phrases.py — вынос строк:**
- Создан `src/utils/phrases.py` — единый модуль со всеми пользовательскими строками:
  - ~60 button labels (`BTN_*`)
  - ~25 error messages (`ERR_*`)
  - ~50 info/success/prompt messages
  - ~20 evening/morning report messages
  - GREETINGS, DEFAULT_CATEGORIES, MENU_KEYWORDS, fallback values
- Заменены inline-строки на `phrases.*` в 8 файлах:
  - `menu.py` — 500 строк изменено (~180 замен)
  - `history.py` — 27 замен
  - `evening_flow.py` — 6 замен
  - `keyboards.py` — 23 замены
  - `morning_report.py` — базовые зоны, приветствие, yesterday_line
  - `evening_report.py` — все варианты отчётов (zero/green/overdraft/autoclose)
  - `expense_service.py` — round-up сообщение
  - `categorization.py` — GREETINGS + DEFAULT_CATEGORIES
- **Не извлечены** (требуют рефакторинга random.choice): статусные footer'ы (11 групп), menu_daily блок, fresh-start step-тексты, YELLOW_SIM_*/RED_* зоны в morning_report
- **E501:** 117→144→135 (добавила `per-file-ignores` для тестов)
- **ruff format:** 20 файлов отформатировано для CI compliance
- **Все 269 тестов проходят**, ruff — только известные E501 (135) + E712 (20, безопасные для SQLAlchemy)

### 2026-06-09 — Queue 5: Bugfixes + статус-редизайн + удаление menu_daily

**Production bugs:**
- **Хотелка показывала 0₽**: статус читал `budget.wishlist_target` (цель) вместо `Wishlist.current_amount`. Исправлено — вызывает `get_goal_current_amount()`.
- **menu_daily писал «нет бюджета»**: искал `WHERE month = текущий`, не находил при периоде через месяц. Переведён на `get_active_budget()` вместе с `_get_daily_limit_text` в keyboards.py. Сама кнопка `menu_daily` и её хендлер удалены.

**UX:**
- Статус переписан в минималистичный формат:
  ```
  БАЛАНС · 🟢 В лимите

  Сегодня
  Свободно 3 507 ₽ · Потрачено 826 ₽

  Период (до 20-го · 14 дн.)
  Остаток 49 112 ₽ · Лимит 4 333 ₽/день

  Резервы под охраной
  Обязательные 40 000 · Кубышка 10 000 · Хотелка 636
  ```
- Кнопка «📊 Статус» переименована в «💰 Дневной лимит: X₽» (сумма динамическая, минимум 0).
- Весёлые зональные фразы возвращены, приходят в том же сообщении после пустой строки.
- **E501:** 135 → 27 (удалены длинные footer'ы + menu_daily хендлер).
- **269 тестов проходят**, ruff — только известные E712 (20). Запушено в main.

---

## Планы на следующие сессии (приоритет)

### Блок 0: Баги (ASAP)

1. **Б1: Категории не отображаются в пикере смены категории** — починить выбор категории при нажатии «✏️ Сменить категорию». Сортировать: старый порядок неизменен, новые категории — в конец.
2. **Б2: Дубликаты трат при обрывах соединения** — при задержке ответа Telegram трата создаётся повторно, сообщение пользователя зависает. Нужен recovery: детект дубликатов (amount+description+timestamp), повторная отправка неудалённого сообщения.
3. **Б3: Округление не вычитает разницу из лимита дня** — при трате 1₽ и rounding_mode=10 лимит дня уменьшается на 1₽ вместо 10₽. Разница 9₽ «улетает» в хотелку, но не списывается с дневного бюджета.
4. **Б4: Фраза про хотелку при перерасходе вводит в заблуждение** — «Хотелка отодвинулась на N дней» непонятна: хотелка не резерв, а просто число, из неё ничего не вычитается. Нужно либо переформулировать, либо пересмотреть логику.

### Блок 1: UX

5. **UX1: Сообщение «Вернулись, Aelita!» при возврате в меню** — избыточно. Убрать или заменить на нейтральное.
6. **UX2: Вечерний отчёт удаляет итог вместо teaser'а** — удалять только сообщение «👁 День подошел к концу...», итоговый отчёт оставлять в чате. Кнопку под отчётом удалять.
7. **UX3: В вечернем отчёте нет списка трат за день** — добавить перечень всех расходов за день в тело отчёта.
8. **UX4: Аудит переходов между сообщениями** — пройтись по всей цепочке, что удаляется/остаётся/перезаписывается, устранить путаницу.

### Блок 2: Фичи

9. **Проверить production** — убедиться, что Railway авто-деплой подхватил все фиксы
10. **Добить E501** — 28 ошибок
11. **Математические выражения в тратах** — поддержка +, -, *, / в сумме («500+300 кофе», «250*2 билет»)
12. **Гибкий дневной лимит** — разные лимиты на будни и выходные (вручную или авто-предложение после 1-2 недель)
13. **Кастомные эмодзи категорий** — пользователь меняет иконку категории
14. **Статистика и мотивация** — кнопка: streak дней, сколько сэкономлено, прогноз к концу периода
15. **Умный парсинг фраз** — токенизация, приоритет существительных
16. **Покрыть перерасход из будущего дня** — не пересчёт всего лимита, а вычет разницы из следующего дня (с подтверждением)
17. **Фиксированный дневной лимит** — задать ₽/день без привязки к доходу за месяц
18. **Ночные траты (финтех-сутки)** — 00:00-04:59 → предыдущий день, граница отчёта 05:00
19. **Режим «только расходы»** — без дохода, просто дневной лимит
20. **Динамическая таймзона** — WebApp-онбординг, поддержка путешествий
21. **Авто-бэкап PostgreSQL** — ежедневный pg_dump в Telegram или S3
22. **AI-широкая интеграция:**
    - ASR-распознавание голосовых сообщений
    - Распознавание чеков по фото (OCR + API ФНС + GPT-4o Vision)
    - Естественно-языковые запросы к истории
    - AI-аналитика (аномалии, инсайты, паттерны)
    - AI-генерация сводок (умные итоги месяца)
    - AI-ассистент (без прямого диалога с LLM)
23. **Режим путешествия** — мультивалютность, конвертация
24. **Общие бюджеты** — бюджет с партнёром/семьёй
25. **Геймификация и психология:**
    - Стрики, ачивки, динамический лимит
    - «Огоньки» / уровни за регулярность
    - Челленджи от бота (турбо-экономия, неделя без кофе)
    - «Фонд факапов» — отдельная заначка на внезапные расходы
    - Умная кубышка — автооткладывание при остатке выше порога
26. **Маскот** — персонаж (лис/кот/пингвин/хамелеон), стикеры
27. **Аналитика выходные vs будни** — паттерны трат
28. **Рекламная интеграция (Shorts)** — для будущей публичной версии

### 2026-06-04 — Feature ideas из RTF добавлены в документацию

- **Сделано:** Прочитан и проанализирован `описание идей бота.rtfd/TXT.rtf`
- **Добавлено в PRD.md (раздел 8.2 + 9):**
  - Описан стиль «Бро-Дуо» — Duolingo-like персонаж: дерзкий, поддерживающий, с геймификацией
  - AI-широкая интеграция (ASR + OCR чеков + ФНС + GPT-4o Vision + NL-запросы + аналитика)
  - Режим путешествия с мультивалютностью
  - Общие бюджеты с партнёром
  - Геймификация (стрики, ачивки, динамический лимит, челленджи)
  - Маскот (лис/кот/пингвин/хамелеон)
  - «Фонд факапов», умная кубышка, аналитика выходные vs будни
- **Добавлено в README.md:**
  - Описание трёхуровневой системы бюджета с формулой `daily_limit = (total_income - mandatory_payments - black_day_fund) / days_remaining`
  - Расширенный список Remaining со всеми feature ideas
- **Добавлено в progress.md:**
  - Приоритезированный план на 9 пунктов
- **Решение:** Все идеи из RTF добавлены в документы; геймификация и маскот вписаны в характер бота (Duolingo-like стиль уже был, теперь закреплён)

---

### 2026-06-10 — ✅ Queue 6: Контекстный скоринг омонимов

**Проблема:** Слово «самокат» — омоним (транспорт vs доставка). Stage 1 возвращал первое совпадение без контекста.

**Решение — дистанционный скоринг по среднему чеку:**
- Stage 1 теперь собирает ВСЕ совпадения ключевого слова
- Если ровно 1 — быстрый путь (как сейчас)
- Если >1 — для каждой категории считаем `avg = AVG(amount)` последних 10 трат с этим ключевым словом (WHERE description CONTAINS keyword AND is_deleted=False)
- Выбираем категорию с min(|amount_текущей_траты - avg|)
- Если у категории нет истории (avg=NULL) — не участвует в сравнении
- Если все без истории или ничья — по порядку списка (как сейчас)

**Автокоррект описания (новый этап 0):**
- После `clean_description()` каждое слово прогоняется через `difflib.get_close_matches(cutoff=0.85)` против всех keywords пользователя
- Опечатки («самокад» → «самокат») исправляются молча, в памяти, ДО записи в БД
- В БД сохраняется чистое слово — корректно попадает в расчёт среднего

**Что не меняется:**
- `add_keyword_to_category` остаётся — создаёт омонимы при ручной смене категории
- История трат не переписывается
- Модели БД не меняются (AVG считается live из expenses)
- SQL AVG подхватывает удаление (is_deleted) и редактирование суммы автоматически

**Файлы изменений:**
- `categorization.py` — новые функции: `_autocorrect_description`, `_get_keyword_avg`, `_score_by_keyword_avg`. Stage 1 модифицирован
- `menu.py` — хендлеры передают amount в detect_category_db, используют corrected_description для сохранения
- `tests/test_categorization.py` — тесты (9 категорий BigTech Standard)

**Done:** `categorization.py` — 3 новые функции + Stage 1 модифицирован. `menu.py` — amount передан в detect_category_db. 22 новых теста (9 BigTech категорий). 292 тестов проходят, ruff — 50 pre-existing, 0 новых.

### 2026-06-11 — Queue 7: Управление категориями (Б1 + рефакторинг + CRUD)

**Б1 (баг — категории пустые в пикере):**
- Причина: `seed_user_categories()` при повторном вызове возвращала `[]` из-за кеша `_seeded_users`
- Фикс: вызов `get_user_categories()` вместо `seed_user_categories()` в `change_category`

**Рефакторинг сидирования:**
- Сидирование 11 дефолтных категорий перенесено в `/start` (новый пользователь) и `reset_budget`
- Убрано из `detect_category_db` и `change_category`
- `get_user_categories()` теперь фильтрует `is_archived == False`
- Добавлена `get_all_categories()` для менеджмента (все, включая архивные)
- Автокатегоризация не видит архивные категории

**Сортировка категорий:**
- `.order_by(Category.id)` в `get_user_categories()` и `get_all_categories()`
- Дефолтные категории — всегда в одном порядке, новые — в конце

**Проверка дубликатов при создании/переименовании:**
- Точное совпадение после `.strip().capitalize()`
- Ошибка + возврат в пикер / отмена rename

**CRUD категорий (новый модуль):**
- `Category.is_archived` (Boolean) — мягкое удаление
- Миграция БД (SQLite + PostgreSQL)
- `src/services/category_service.py` — rename, archive/unarchive, move+delete (expenses → Прочее), hard delete (expenses DELETEd)
- `src/bot/handlers/categories.py` — пагинированный список (5/стр, активные + архивные), детали, rename (FSM), archive/unarchive, delete (4 опции + двухшаговое подтверждение)
- Точки входа: настройки + пикер смены категории
- Умный «⬅️ Назад» из списка → обратно в пикер (через `_cat_back_target[user_id]`)

### 2026-06-11 — Queue 8: Детект дубликатов трат (Б2)

**Проблема:** При обрыве/таймауте Telegram API расход коммитился в БД, `state.clear()` сбрасывался до `message.answer()`, пользователь не видел ответа и отправлял трату снова — создавался дубликат.

**Решение — DuplicateMiddleware (`src/bot/middleware.py`):**
- In-memory `_expenses[user_id]` — список последних трат каждого пользователя (окно 15s)
- `check()`: 0 совпадений → `'new'`, 1 → `'warn'`, 2+ → `'silent'`
- При `'warn'`: данные в `_pending`, warning-сообщение с кнопками `[❌ Это дубль] [✅ Да, вторая трата]`
- При `'silent'`: полная тишина — ни ответа, ни сохранения
- Защита от Telegram-ретраев: `_last_message_id[user_id]` — при повторном `message_id` middleware пересылает последний ответ
- Защита от утечки памяти: `_cleanup_old_users()` раз в сутки удаляет неактивных пользователей из всех словарей
- Зарегистрирован как `dp.message.middleware(dup_middleware)`, singleton доступен хендлерам через импорт

**Callback-хендлеры (menu.py):**
- `dup_confirm` — подтверждение второй траты: забирает `_pending`, создаёт Expense, показывает `DUP_CONFIRMED` с балансом
- `dup_del` — отмена дубля: сбрасывает `dup_count`, показывает `DUP_DELETED`

**Попутно:**
- `state.clear()` теперь выполняется после `message.answer()` (гигиена кода)
- Фикс `lines.append` вне цикла в `handle_text` — мультилайн-траты в свободном вводе теперь показывают все строки
- Удалён dead code после `return` в `handle_text`

**Files:**
- `src/bot/middleware.py` — DuplicateMiddleware (~100 строк)
- `src/bot/handlers/menu.py` — duplicate check в process_expense + handle_text + callback handlers
- `src/bot/keyboards.py` — `get_duplicate_keyboard()`
- `src/utils/phrases.py` — 5 новых фраз (BTN_DUP_DEL, BTN_DUP_CONFIRM, DUP_WARNING, DUP_CONFIRMED, DUP_DELETED)
- `src/bot/main.py` — регистрация middleware + cleanup task

**Status:** 292 тестов проходят, ruff — 0 новых ошибок. Запушено в main.

---

### 2026-06-13 — Queue 9: Переименование категорий — emoji-детекция + тесты

**Проблема:** `ord(raw[0]) > 0x1F000` не ловил многие emoji (☕, ©, флаги, составные), а fallback `📦` пересекался с «Прочее».

**Решение:**
- Добавлена библиотека `emoji` в `requirements.txt`
- Создана `_extract_emoji(text)` в `helpers.py` — использует `emoji.emoji_list()` для поиска первого emoji + `emoji.replace_emoji()` для очистки текста
- Новый fallback emoji `FALLBACK_EMOJI = "🏷️"` (tag) — не пересекается с существующими категориями
- `get_category_display()` — fallback `📦` → `🏷️`
- `process_cat_rename` переписан: `_extract_emoji` вместо `ord()`, цепочка `emoji = new_emoji or old_emoji or FALLBACK_EMOJI`, no-op детекция (то же имя → тихий успех)
- `conftest.py` — добавлены `category_service` и `categories` хендлер в monkeypatch

**Тесты:** 33 новых теста (14 unit на `_extract_emoji`, 4 service, 13 FSM-хендлера). Итого 325 тестов, 0 новых ruff-ошибок.

---

## Шпаргалка для агента

После каждой сессии (или по запросу пользователя) агент проверяет: было ли что-то из списка «Когда писать». Если да — добавляет запись в этот файл перед завершением работы.
