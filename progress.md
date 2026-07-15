# progress.md — Архитектура и ключевые решения

> Не хронология commit'ов, а каркас системы и почему код именно такой.

---

## Текущий статус и фокус

**Стабильная основа:** парсинг расходов, категории, дубликаты, утренние/вечерние отчёты, онбординг, округление, математические выражения в тратах.  
**Активно:** —  
**Ближайшее:** B7, B9, B10, B11  
**В планах:** логика обязательных платежей (обнуление после оплаты), E501, UX5-UX7, F4-F9  

---

## Decision Log (ADR)

### HTML-инъекция через first_name: убрать {name} из косметических фраз (2026-07-10)
**Проблема:** глобальный `parse_mode="HTML"` в диспетчере — все format-строки рендерятся как HTML. Если пользователь задаст `first_name` с HTML-тегами (`<a href="...">`), они выполнятся в сообщении бота. 

**Оценка риска:** `first_name` приходит от Telegram, не от пользователя напрямую, но Telegram не экранирует HTML в `first_name`. Злоумышленник может сменить имя через настройки → XSS-like injection в сообщениях бота.

**Решение:**
1. Убрать `{name}` из всех 22 косметических фраз (приветствия, подтверждения, хелпы).
2. Удалить `format(name=user_name)` и переменную `user_name` из 20+ мест в `menu.py`.
3. Оставить `safe()` только в 4 UI-точках, где имя действительно добавляет ценности:
   - Заголовок настроек (`⚙️ {user_name}, что меняем?`)
   - Подтверждение хотелки (`✅ Готово, {user_name}! Хотелка: ...`)
4. Удалить мёртвый `FALLBACK_NAME`.

**Почему не `safe()` везде:** проще вообще не вставлять имя, чем помнить о `safe()` в каждой format-строке. 4 места с `safe()` легко контролировать. «Бро»-стиль бота допускает безличные сообщения.

---

## Decision Log (ADR)

### UX-рефакторинг бюджета: замена Critical Reset на «Пересчитать лимит» (2026-07-10)
**Проблема:** пользователь запуталась между «Добавить доход», «Обновить доход» и «Начать с чистого листа». Первые два распределяли сумму на ВСЕ дни периода, третий (Critical Reset) — на оставшиеся, но был спрятан за 3 зонами и назывался устрашающе. Плюс баг: `daily_limit` в модели делил `free_money` на `_period_total_days`, а не на `days_remaining`.

**Что сделано:**
1. **Settings:** две кнопки схлопнуты в одну «Изменить бюджет» → выбор: «Дополнительный доход» (add_income) или «Остаток на карте» (recalc).
2. **Morning Report:** кнопки «🚀 Начать с чистого листа» / «🔄 С чистого листа» → «🔄 Пересчитать лимит». Без зон — сразу запрос суммы → применение.
3. **Статус:** все кнопки пересчёта убраны. Оставлены только кнопки «Использовать Кубышку».
4. **Баг `daily_limit`:** при `free_money > 0` теперь делит на `max(self.days_remaining, 1)`, а не на `_period_total_days`.
5. **Удалены:** `CriticalReset`, `FreshStart` (FSM-классы и хендлеры), 3-зонная логика, `FRESH_START_PROMPT/GREEN/YELLOW/RED`, `CANCEL_CRITICAL_RESET/FRESH_START`.

**Почему:** пользовательский сценарий «вот сколько денег на карте, пересчитай на оставшиеся дни» — основной. 3-зонный ре-онбординг (FreshStart) был избыточен и пугал. Единый flow без ветвления проще и предсказуемее.

### B6: Пересчёт лимита — убрано вычитание обязательных платежей + фикс периода (2026-07-14)
**Проблема (1):** `reconcile_budget_with_reality` вычитала `mandatory_payments` и `black_day_fund` из `total_balance`, который пользователь вводит как «остаток на карте сейчас». Если обязательные уже оплачены (а деньги потрачены), повторное вычитание давало `money_for_life = 0` → лимит 0 ₽/день.
**Решение (1):** `money_for_life = max(total_balance, 0)` — введённая сумма используется как есть.

**Проблема (2):** Обе функции (`reconcile_budget_with_reality` и `apply_reconciliation`) искали бюджет только по `month == get_msk_now().strftime("%Y-%m")`. При `period_start_day > today.day` активный бюджет хранится под прошлым месяцем (`YYYY-MM`), поэтому бюджет не находился → default `(0.0, 1, 0.0, ...)`.
**Решение (2):** Обе функции переведены на поиск через `get_active_budget()` / аналогичную логику с `month.in_([this_month, last_month])`. Теперь бюджет находится даже при переходе через границу месяца.

### B8: Inline-клавиатура Morning Report не чистится (2026-07-15)
**Проблема (1):** `_last_keyboard` = `TTLCache(maxsize=1024, ttl=3600)`. Между утренним отчётом (08:00) и следующим действием пользователя могло пройти >1 часа — запись протухала, `KeyboardCleanupMiddleware` не находил message_id для очистки.
**Решение (1):** Заменил `TTLCache` на `dict[int, int]`. Записи живут, пока не будут явно `pop()`-нуты `KeyboardCleanupMiddleware` при следующем действии пользователя.

**Проблема (2):** `edit_rich_message` в `monthly_summary.py` безусловно писал `_last_keyboard[chat_id] = message_id`, затирая старую запись (например, message_id утреннего отчёта). После этого `KeyboardCleanupMiddleware` при клике на утренний отчёт чистил клавиатуру у Monthly Summary, а не у отчёта.
**Решение (2):** В `edit_rich_message` и `send_rich_message` — перед записью нового `message_id` сначала `pop()` старого и `edit_message_reply_markup(reply_markup=None)`, если это другой message_id.

### B12: Кнопка «В главное меню» в отчётах дублирует ReplyKeyboard (2026-07-15)
**Проблема:** Во всех отчётах (Morning Report, Evening auto-close, Evening flow) была кнопка «⬅️ В главное меню» с `callback_data="report_back"`. После внедрения ReplyKeyboard (Phase 2, флаг `EXPENSE_SIMPLE_CHECK`) меню всегда доступно внизу чата, кнопка стала бесполезна. При `EXPENSE_SIMPLE_CHECK=True` `report_back` был no-op, при `False` — дублировал ReplyKeyboard.

**Решение (условное от флага):**
- `EXPENSE_SIMPLE_CHECK=True` (ReplyKeyboard active) → `BTN_BACK_MAIN` **отсутствует** во всех отчётах, `report_back` → acknowledge без клавиатуры.
- `EXPENSE_SIMPLE_CHECK=False` (inline-меню) → `BTN_BACK_MAIN` **присутствует**, `report_back` → `BACK_NAV` + `get_main_menu_keyboard()`.
- Изменённые файлы: `morning_report.py`, `evening_report.py`, `evening_flow.py`, `menu.py`.

---

## 📌 Feature Flags

| Флаг | По умолчанию | Что контролирует |
|------|-------------|------------------|
| `EXPENSE_SIMPLE_CHECK` | `True` | `True` → ReplyKeyboard (persistent menu внизу чата), inline-меню скрыто, чеки трат без лишних кнопок. `False` → inline-клавиатуры, кнопка «В главное меню» в отчётах. |
| `BOT_TOKEN` | — | Telegram Bot API токен |
| `DATABASE_URL` | `sqlite+aiosqlite:///tratobot.db` | Строка подключения к БД (SQLite dev / PostgreSQL prod) |

---

## Архитектура

### Стек
- **Python 3.11+**, **Aiogram 3.x**, **SQLAlchemy 2.x** (async), **SQLite** (dev) / **PostgreSQL** (prod)
- **Middleware:** `AutoCleanKeyboard` (трекинг клавиатур), `RateLimit`, `DuplicateMiddleware`
- **Tests:** pytest + in-memory SQLite + monkeypatch `async_session_maker`

### Карта проекта
```
src/
├── bot/
│   ├── handlers/       # menu.py, evening_flow.py, history.py, categories.py ...
│   ├── middleware.py    # AutoCleanKeyboard, RateLimit, Duplicates
│   └── rich_api.py     # Rich-отправка через raw HTTP (для Monthly Summary, Morning)
├── services/
│   ├── expense_service.py  # Парсинг, CRUD трат, parse_expense_text()
│   ├── categorization.py   # Детект категорий по описанию
│   ├── evening_report.py   # Вечерний flow
│   └── morning_report.py   # Утренний отчёт
├── db/
│   └── models/         # Expense, Budget, Category, Wishlist, etc.
└── utils/
    ├── helpers.py       # _MathParser, _preprocess_math, parse_amount, _extract_emoji
    └── phrases.py       # Все строки пользовательского UI
```

### Ключевые сущности
- **Expense**: amount, description, category_id, date, is_deleted
- **ExpenseParseReport**: is_valid, amount, description, was_corrected, correction_hint, error_type, error_detail (не ORM, датакласс)
- **MultiExpenseParseResult**: reports: list[ExpenseParseReport], is_fully_valid
- **Category**: name, emoji, telegram_id, is_archived
- **DuplicateMiddleware**: in-memory кэш (15s окно), 3 escalation (success → warn → silence)

---

## Decision Log (ADR)

### Математические выражения в тратах (2026-07-08)
**Что сделано:** кастомный рекурсивный парсер `_MathParser` в `helpers.py`, который разбирает `500+300 такси` → сумма 800, описание «такси». Без `eval()`.

**Почему не eval:**
`eval("500+300")` — встроенная Python-функция, выполняющая строку как код. Если пользователь напишет `__import__('os').system('rm -rf /')+500`, eval выполнит это. Наш парсер видит только числа и операторы — всё остальное вызывает `_MathParseError`. Безопасность на уровне дизайна, не костыля.

**Архитектура парсера (recursive descent):**
```
parse_expr → parse_term → parse_factor
```
- `parse_expr` обрабатывает `+`/`-` (низший приоритет)
- `parse_term` обрабатывает `*`/`/` (средний приоритет)  
- `parse_factor` обрабатывает числа, скобки, унарный `+`/`-` (высший приоритет)
- Токены: NUMBER / PLUS / MINUS / MUL / DIV / LPAREN / RPAREN / EOF

**Два режима:**
- `_eval_math(text)` — полный разбор, всё строка — математика. Используется в `parse_amount()` (онбординг, редактирование бюджета).
- `_parse_math_prefix(text)` — разбор до первого не-математического символа, возвращает `(total, rest)`. Rest идёт в описание. Используется в `parse_expense_text()`.

**Авто-коррекция (`_preprocess_math`):** три правила, применяются последовательно:
1. Хвостовой оператор → `500+300+` → `500+300`
2. Баланс скобок → `(500+300` → `(500+300)`, `500+300)` → `500+300`
3. Двойные знаки → `500++300` → `500+300`, `500+-300` → `500-300`

**Edge cases (все закрыты):**
- Скобки: `(500+300)*2`, `(500+300)`, `1+1)`, `7+2)-20`
- Унарный +/–: `-5`, `+5`, `5+-3`, `5*-3`
- Научная нотация: `1e5+2e5`, `5e-3`, `2E5`
- Ноль из math: `5-5` → «нулевая сумма», `(7+2)-20` → «отрицательная сумма»
- RecursionError на >950 скобок → MATH_ERROR

**Объём:** ~300 строк ядра (токенизатор + парсер + препроцессор + валидация) + ~120 строк изменений в хендлерах + ~50 строк новых тестов.

### BigTech-паттерны ошибок
- **Pattern 2 (MATH_ERROR):** блок траты, `<code>` для копирования, 3 retry → clear state. Для: деление на ноль, отрицательная/нулевая сумма, неисправимая каша
- **Pattern 1 (was_corrected):** авто-коррекция (скобки, хвостовые операторы, двойные знаки), трата сохраняется, предупреждение + кнопка «✏️ Исправить» (через `exp_edit:{id}`, DRY). Для: лишняя скобка, хвостовой `+`, двойные знаки

### Callback data — только ID
- **Почему:** Telegram лимит 64 байта, защита от инъекций
- **Формат:** `exp_edit:{id}`, `change_cat:{id}`. Никогда сырой текст

### Научная нотация (1e5) — добавлена в NUMBER regex
- **Почему:** `1e5+1e5` до фикса давало 1.0 + мусор как описание (`e5+1e5`)
- **Что:** `\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?` — в _TOKEN_SPEC и _fallback_first_number

### Zero / negative из math — прямой error вместо fallback
- **Почему:** `7+2)-20` → коррекция `7+2-20` → -11. Раньше выдёргивало первое число (7), теперь честно: «отрицательная сумма»

### current_text_end — возвращает start, а не end
- **Почему:** `1+1)` — RPAREN был включён в «съеденный» диапазон, скобка бесшумно исчезала. Фикс: `tokens[self.pos][2]` вместо `[3]`

### Message Lifecycle Policy («Конституция интерфейса»)
- **Callback:** только `edit_text()`, никогда `delete()`
- **User message:** только `answer()`, не редактировать и не удалять
- **Teaser (22:00):** единственное исключение на delete, с `_last_keyboard.pop()`
- **Rich API:** ручной трекинг `message_id` в `_last_keyboard` (обходит middleware)

### AutoCleanKeyboardMiddleware вместо двух систем
- **Почему:** `_track_keyboard` (TTLCache) и `_save_msg_id` (FSM) не координировались → `TelegramBadRequest` на edit удалённого
- **Решение:** единый middleware, перехватывает `message.answer()`/`edit_text()` на MenuRouter, чистит предыдущую клавиатуру

### Единый _save_expenses_from_parsed_list
- **Почему:** `process_expense` + `handle_text` дублировали ~90 строк
- **Решение:** вынесено в сервис, каждый хендлер — ~20 строк

---

## Правила и ограничения

- **Все UI-строки** — только в `src/utils/phrases.py`, никогда хардкод
- **Тесты бизнес-логики** — обязательны. Покрытие: парсинг, helpers, категории, сервисы
- **SQLAlchemy `== False`** — не менять на `not` (ruff E712); `--unsafe-fixes` ломает код
- **Нет FSM для редактирования** — контекст в callback data (до 64 байт)
- **Отрицательные суммы** — не сохраняются, возвращают `MATH_ERROR` с деталью
- **Callback → delete запрещён** (Message Lifecycle Policy, п. 12.3 RULES.md)

---

## Известные проблемы и костыли

- **Rich API (Monthly Summary, Morning):** идёт raw HTTP, минуя `AutoCleanKeyboardMiddleware`. Ручной трекинг в `_last_keyboard` — источник рассинхронизации
- **Overflow в math-парсере:** `huge*big` может дать `inf`. `math.isfinite` есть только в `parse_amount()`; `parse_expense_text` не проверяет
- **Парсинг multiline:** строки без цифр игнорируются, но атомарность только по MATH_ERROR (если хоть одна строка MATH_ERROR — не сохраняется ничего). Другие ошибки не блокируют
- **`duplicate_middleware`:** защита по `message_id` работает, но 15s окно — эвристика; долгая ручная отправка одной и той же траты через >15s пройдёт как новый дубликат
- **`_fallback_first_number` в corrected path:** вызывается, только если `_parse_math_prefix(fixed)` вернул None (нет math-токенов в corrected). Если есть числа, но нет операторов — вытаскивает первое число, что может не совпадать с ожиданием
