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

### 2026-06-03 — Security audit + foundation
- **Решение:** Созданы PRD/RULES/progress/README. Стиль — ироничный напарник. SQLAlchemy оставлена. Railway как хостинг.
- **Аудит безопасности:** 19 уязвимостей (3H, 9M, 7L) — все закрыты. Ключевое: `.env` удалён, `parse_amount()` с валидацией, миграции с allow-list, RateLimitMiddleware, `safe(html.escape())`, автовыход из FSM после 3 ошибок, лимиты длины (500/255).
- **Создано:** `src/utils/helpers.py`, `src/bot/middleware.py`
- **🧠 Важно:** `--unsafe-fixes` для E712 нельзя применять к коду с SQLAlchemy (ломает `is_deleted == False`).

### 2026-06-03/04 — Тесты (Очереди 1-3)
- 133 теста чистых функций (Очередь 1) + 59 с моками БД (Очередь 2) + 77 FSM/integration (Очередь 3). Итого ~269 тестов.
- BigTech Standard закреплён в RULES.md (9 категорий сценариев).
- `conftest.py` с in-memory SQLite, фикстурами, monkeypatch `async_session_maker`.
- Пре-коммит + CI (GitHub Actions) — ruff (lint+format), mypy, pytest.

### 2026-06-04 — Queue 4: phrases.py + datetime bugfix
- Все строки вынесены в `src/utils/phrases.py` (~180 замен в 8 файлах).
- Production: PostgreSQL не принимал offset-aware datetime → naive UTC (`_utcnow()`).

### 2026-06-09 — Queue 5: Bugfixes + статус-редизайн
- Хотелка читала `wishlist_target` вместо `Wishlist.current_amount` — исправлено.
- menu_daily не находил бюджет при переходе месяца — переведён на `get_active_budget()`.
- Статус → минималистичный формат. Кнопка «📊 Статус» → «💰 Дневной лимит: X₽».
- E501: 135 → 27.

### 2026-06-04 — Feature ideas из RTF
- Добавлены в PRD.md: стиль «Бро-Дуо», AI-интеграция, геймификация, маскот, режим путешествия, общие бюджеты и др.

### 2026-06-10 — Queue 6: Контекстный скоринг омонимов
- Stage 1 собирает все совпадения → AVG(amount) последних 10 трат → min(|amount - avg|).
- Автокоррект описаний через difflib (cutoff 0.85) до записи в БД.
- 22 новых теста. Итого 292 теста.

### 2026-06-11 — Queue 7: Управление категориями (Б1 + CRUD)
- Б1: `seed_user_categories()` → `get_user_categories()` в пикере.
- Сидирование вынесено в `/start`. CRUD: `category_service.py` + `categories.py`.
- `is_archived`, сортировка по id, проверка дубликатов.

### 2026-06-11 — Queue 8: Детект дубликатов трат (Б2)
- `DuplicateMiddleware`: in-memory кэш (15s окно), 3 эскалации (success → warn → silence).
- Защита от Telegram-ретраев по `message_id`. Фоновая очистка раз в сутки.

### 2026-06-13 — Queue 9: Emoji-детекция
- Библиотека `emoji`, `_extract_emoji()` в helpers.py, fallback `🏷️`. 33 теста. Итого 325.

### 2026-06-15 — Queue 10: Дубль эмодзи в категориях
- `get_category_display()` везде вместо `cat.name`. Инлайн-кнопки 2/ряд вместо пагинации. Итого 327.

### 2026-06-15 — Queue 11: B3 — Округление вычитается из лимита
- `compute_rounding()`: `effective = ceil(amount/mode)*mode`, разница в хотелку. `try_apply_round_up` удалён. Итого 329.

### 2026-06-15 — Queue 12: B4 — Переформулировка overdraft
- Хотелка → «Остаток периода — N дн.». Добавлены F1-F3, UX2-UX3 в бэклог.

### 2026-06-15 — Queue 13: B5 — Silent drop при офлайн-очереди
- Убран тихий rate-limit (0.7s между сообщениями), оставлен burst (5/3с).

### 2026-06-19 — Queue 14: Morning report recovery
- Таблица `daily_reports_log`, startup check (05-12 МСК), misfire_grace_time=4ч.

### 2026-06-19 — Queue 15: Удаление категории с выбором целевой
- Инлайн-пикер активных категорий вместо авто-переноса в «Прочее».

### 2026-06-19 — Queue 16: Soft Correction + чистые чеки (Phase 1)
- FSM не сбрасывается при ошибках категории. `EXPENSE_SIMPLE_CHECK=True` — только кнопка смены категории в чеке.

### 2026-06-19 — Queue 17: Phase 2 — ReplyKeyboard
- Постоянное меню внизу: Добавить трату, Дневной лимит, Статистика, Настройки, Помощь.

### 2026-06-21 — Queue 18: Inline-меню отключено при SIMPLE_CHECK
- `get_main_menu_keyboard()` → None. Убраны «👇». Только ReplyKeyboard. 330 тестов.

### 2026-06-23 — Queue 19: Monthly Summary
- Ежемесячный отчёт с тотемами (6 персонажей + Чебурашка), моноширинной таблицей, навигацией по месяцам. Вместо утреннего отчёта в день после period_start_day. 329 тестов.

### 2026-07-02 — UX1: Убрано «Вернулись, Aelita!»
- `BACK_NAV` → `\u200b` (zero-width space). Т-Банк минимализм.

### 2026-07-02 — UX1.5: Удалены inline-кнопки «В меню» при SIMPLE_CHECK
- Убраны все inline-кнопки, ведущие в меню, во всех хендлерах. Контекстная навигация сохранена.
- Починено: `back_from_category_change` и `category_back_to_list` не чистили FSM.

---

### 2026-07-05 — UX4 Audit: 4 бага закрыто

**Контекст:** Проведён аудит всех message-переходов (что удаляется/остаётся/перезаписывается). Найдено 8 багов — задокументированы в `bugs_ux4.md`. Закрыто 4.

**Bug #1: Дубликат кода process_expense / handle_text (HIGH)**
- **Решение:** Вынесен общий `_save_expenses_from_parsed_list()`. Каждый хендлер — ~20 строк.

**Bug #3: menu_help не чистит FSM (MEDIUM)**
- **Решение:** Добавлен `await state.clear()`.

**Bug #4: menu_settings не чистит FSM (MEDIUM)**
- **Решение:** Добавлен `await state.clear()`.

**Bug #6: Orphaned-клавиатура после save_new_category (LOW)**
- **Решение:** `_track_keyboard()` в промпте → `_cleanup_keyboard()` при успехе.

**Новый файл:** `bugs_ux4.md` — трекер всех найденных UX4-багов (4 open: #2, #5, #7, #8).

**329 тестов проходят, 0 новых ruff-ошибок.**

---

### 2026-07-05 — Bug #2 fix: Единая система отслеживания клавиатур (AutoCleanKeyboardMiddleware)

**Проблема:** Две независимые системы — `_track_keyboard`/`_cleanup_keyboard` (TTLCache) и `_save_msg_id`/`_cleanup_old_buttons` (FSM-context) — не координировались → `TelegramBadRequest` при edit удалённого сообщения.

**Решение:** Создан middleware `AutoCleanKeyboardMiddleware` (`src/bot/middleware.py`):
- Перехватывает все `message.answer()`, `message.edit_text()`, `message.edit_caption()` на `MenuRouter`
- Автоматически трекает `message_id` каждого сообщения с `reply_markup`
- При следующей отправке с новой клавиатурой — редактирует предыдущее: `reply_markup=None`
- TTLCache: `maxsize=512`, `ttl=600` (10 мин)

**Онбординг переведён на общую систему:**
- Удалены `_save_msg_id()` / `_cleanup_old_buttons()` из `menu.py`
- Удалена передача `msg_id` через FSM-контекст в `_finish_onboarding`
- `_build_status()` — убран ручной `_track_keyboard` / `_cleanup_keyboard`

**Файлы:**
- `src/bot/middleware.py` — новый класс `AutoCleanKeyboardMiddleware`
- `src/bot/handlers/menu.py` — удалены 2 функции + 6 вызовов

**bugs_ux4.md:** Bug #2 закрыт. Статус: 6/8 закрыто.

**329 тестов проходят, 0 новых ruff-ошибок.**

---

### 2026-07-05 — Bug #5 fix: cancel edit_text вместо delete для reset-состояний

**Проблема:** `cancel` делал `message.delete()` для CriticalReset/FreshStart и `edit_text()` для всех остальных — несогласованный UX + `_last_keyboard` хранил ID удалённого → `TelegramBadRequest`.

**Решение:**
- Заменён `delete()` на `edit_text()` с контекстной фразой:
  - CriticalReset → `CANCEL_CRITICAL_RESET = "❌ Сброс отменен. Данные не были удалены.\n\nГлавное меню:"`
  - FreshStart → `CANCEL_FRESH_START = "❌ Настройка заново отменена. Продолжаем работу с текущими лимитами.\n\nГлавное меню:"`
- Под SIMPLE_CHECK — отправка ReplyKeyboard
- `edit_text()` проходит через `AutoTrackOutgoingMiddleware` → `_last_keyboard` обновляется, `TelegramBadRequest` устранён

**Файлы:** `src/bot/handlers/menu.py`, `src/utils/phrases.py`
**bugs_ux4.md:** Bug #5 закрыт. Статус: 7/8 закрыто.
**329 тестов проходят, 0 новых ruff-ошибок.**

---

### 2026-07-05 — Bug #7 fix: вечерний flow — фидбек + emoji + FSM-проверка

**7а — Фидбек пользователю (evening_flow.py):**
- После ввода траты: `detect_category_db()` → `message.answer("✅ {emoji}{amount}₽ — {desc} записано!")`, auto-clean middleware-ом
- Ошибки (пустой/нераспарсенный ввод): `message.answer()` без `asyncio.sleep/temp.delete` — middleware чистит на следующем шаге
- Убран `import asyncio`
- Сохранение расходов с `category_id` (раньше было без категории)

**7б — FSM-проверка (evening_report.py):**
- `send_evening_teaser` (22:00): проверка `current_state is not None` → если пользователь в любом другом FSM — `continue` (тихо пропускаем)
- `send_auto_close_reports` (23:30):
  - `EveningState.filling` → обычный авто-отчёт
  - Любой другой FSM → `state.clear()` + `phrases.EVENING_TIMEOUT` + отчёт

**Файлы:** `src/bot/handlers/evening_flow.py`, `src/services/evening_report.py`, `src/utils/phrases.py`
**bugs_ux4.md:** Bug #7 закрыт. Статус: 8/8 закрыто.

---

### 2026-07-05 — Bug #8 fix: response_text в dup_middleware.record()

**Проблема:** `dup_middleware.record()` всегда вызывался с `response_text=""`, из-за чего проверка `last.get("response_text")` в `DuplicateMiddleware.__call__()` никогда не срабатывала — Telegram-ретраи по `message_id` не отбивались, трата повторно обрабатывалась.

**Решение:**
- `_save_expenses_from_parsed_list()` (menu.py): `EXPENSE_SAVED_LINE` строится до `record()` и передаётся как `response_text`
- `handle_duplicate_confirm()` (menu.py): `DUP_CONFIRMED` строится до `record()` и передаётся как `response_text`

**Файлы:** `src/bot/handlers/menu.py`, `src/bot/middleware.py`
**329 тестов проходят, 0 новых ruff-ошибок.**

---

### 2026-07-05 — UX2: отчёты не удалять + список трат в teaser'е

**Проблема:** У отчётов не было единой политики жизни сообщений в чате. Teaser (22:00) — только клавиатура убиралась, текст оставался. Кнопки «В меню» на отчётах делали `edit_text()`, заменяя отчёт меню.

**Решение (4 изменения):**
1. **Новый хендлер `report_back`** (`menu.py`): отправляет меню новым сообщением, не трогая отчёт.
2. **Утро (08:00):** кнопка «В меню» → `report_back`. Отчёт остаётся в чате.
3. **Teaser (22:00):** в текст добавлен блок расходов за today под цитатой (`> Сегодня, 5 июля:\n> ☕ Кофе — 450₽`). Новая функция `get_today_expenses_grouped()`.
4. **Автозакрытие (23:30):** teaser целиком удаляется; кнопка «В меню» → `report_back`.

**Файлы:** `src/bot/handlers/menu.py`, `src/services/evening_report.py`, `src/services/morning_report.py`, `src/services/expense_service.py`
**329 тестов проходят, 0 новых ruff-ошибок.**

