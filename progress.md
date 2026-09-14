# progress.md — Архитектура и ключевые решения

> Не хронология commit'ов, а каркас системы и почему код именно такой.

---

## Текущий статус и фокус

**Стабильная основа:** парсинг расходов, категории, дубликаты, утренние/вечерние отчёты, онбординг (2 шага), составные emoji, daily_limit, математические выражения, **Recovery v1-infra (kill-switch off)**.  
**Активно:** День 5.5 — ADR `Recovery≠Recalc≠Savings` + hard clean Кубышки (full, 1 юзер, `black_day_fund` deprecated)  
**Ближайшее:** редактура Утра 1-26 без Кубышки (твои `Бро, ты машина / Красиво / Брооооо`), затем Вечер→Статус  
**В планах:** Dogfooding Recovery (после Hard clean), Dogfooding AI, релиз 5-10 пользователям  

---

## Decision Log (ADR)

### Бот мужского пола: фикс всех фраз (2026-09-01)
**Проблема:** бот обращался к себе в женском роде («я сама разберусь», «не поняла», «если забыла внести», «посмотрела»). Грамматический род не совпадал с мужским персонажем.

**Решение:** все 8 вхождений женского рода в `phrases.py` исправлены на мужской:
1. «я сама разберусь» → «я сам разберусь»
2. «Не поняла...» → «Не понял...»
3. «Если забыла внести» → «Если забыл внести»
4. «посмотрела сколько всего денег» → «посмотрел сколько всего денег»
5. «Я округлил(а) чек и закинул(а)» → «Я округлил чек и закинул»
6. Гендерно-нейтральные (а)-формы в обращении к пользователю («ты забыл(а)», «ты упустил(а)», «ты заходил(а)») заменены на мужской род — единый стиль, без инклюзивных скобок. Бот мужского пола зафиксирован в README.md.

### Новый онбординг — 2 шага (2026-09-02)
**Проблема:** онбординг из 6 шагов (доход → период → обязательные → кубышка → хотелка → округление) требовал от пользователя 4 финансовых решения до того, как он записал хоть одну трату. Это когнитивная нагрузка, противоречащая BigTech-паттернам (Т-Банк — минимализм, Cleo — вход без анкеты, Duolingo — progressive disclosure).

**Решение:**
1. Онбординг сокращён до 2 шагов: доход → период → финал.
2. `waiting_for_income` → `waiting_for_period_start` → `_finish_onboarding` (сразу).
3. Кнопка «Пропустить» на шаге дохода убрана — `income=0` не должно быть достижимо через Skip.
4. Финальный экран — slim-формат: доход + дневной лимит + подсказка «💡 Если захочешь — дополнительные настройки бюджета есть в ⚙️ Настройках.»
5. FSM-состояния `waiting_for_mandatory/black_day/wishlist/rounding` и их хендлеры **не удалены** — нужны для EditBudget и reset_budget.
6. Тесты адаптированы: переходы `waiting_for_mandatory` → `_finish_onboarding`, убраны недостижимые skip-тесты.

**Файлы:** `menu.py:215,661-667,780-793,863,907`, `phrases.py:ONBOARDING_HINT_SETTINGS`, `test_onboarding_fsm.py`

### Удаление округления трат (2026-09-02)
**Проблема:** автоокругление трат (10/100₽) с перечислением сдачи в хотелку оказалось бесполезным и раздражающим — пользователь видит в отчёте сумму, которая не совпадает с реальной тратой, и не контролирует накопление «излишка».

**Решение:**
1. Убраны `compute_rounding`, `get_rounding_mode` из импортов и логики `_save_expenses_from_parsed_list`.
2. `effective = amount` — сумма сохраняется как есть, без округления.
3. Убраны блоки `ROUND_UP` + `add_spare_change_to_goal` в `process_expense` и `handle_text`.
4. Убрана строка «Округление» из экрана настроек.

**Оставлено намеренно** (обратная совместимость, не мешает):
- Поле `rounding_mode` в `UserSettings` — остаётся.
- Функции `compute_rounding` / `get_rounding_mode` / `add_spare_change_to_goal` в сервисах — остаются (используются только тестами).
- Хендлеры `edit_rounding` / `handle_rounding_choice` — зарегистрированы, но не вызываются из UI.

**Файлы:** `menu.py`

### Настройки → Дополнительное планирование (2026-09-02)
**Проблема:** после упрощения онбординга (2 шага) экран настроек показывал 7 кнопок, включая обязательные/кубышку/хотелку/округление, с которыми новый пользователь не знаком. Главный экран был перегружен.

**Решение:**
1. `get_settings_keyboard()` сокращён до 4 кнопок: «Изменить бюджет», «День старта», «Категории», «→ Дополнительное планирование».
2. Новое подменю «Дополнительное планирование» содержит обязательные/кубышку/хотелку (округление удалено ранее).
3. Единые хелперы `_render_settings()` и `_render_advanced_planning()` — оба входа (`menu_settings` callback и reply-кнопка `BTN_SETTINGS`) показывают одинаковый текст «доход + период».
4. Возврат после редактирования из подменю — паттерн `_from_advanced_planning: set[int]` (аналог `_cat_back_target` в categories.py): `adv_*` wrapper-хендлеры добавляют user_id в сет и делегируют в существующие `edit_*`; `save_*` после записи проверяет сет и возвращает в подменю либо в главное меню.
5. `edit_mandatory` / `edit_black_day` / `edit_wishlist` не знают про Advanced Planning — контекст добавляет только wrapper.

**Файлы:** `menu.py`, `keyboards.py`, `phrases.py`, `tests/test_settings_keyboard.py`

### Rollover-защита + blockquote в настройках (2026-09-02)
**Проблема:** при продлении периода старые значения mandatory/black_day/wishlist молча переезжали в новый бюджет — пользователь не знал, что лимит уже посчитан с их учётом. Плюс экран настроек выглядел как голый текст без визуального разделения.

**Решение:**
1. При rollover пользователь видит, что перенесено: «📋 Перенесено из прошлого периода: • Обязательные: 40 000₽ …». Если ничего не перенесено — стандартный `ROLLOVER_CONFIRMED`.
2. Значения читаются из `old` до `save_budget`, `daily_limit` — из нового бюджета после.
3. `safe()` для wishlist_name — защита от HTML-инъекции.
4. `callback.message.delete()` → `edit_text()` — соответствие Message Lifecycle Policy.
5. Доход и период в настройках обёрнуты в `<blockquote>` — Telegram-цитирование с цветной полосой.

**Файлы:** `menu.py`

### Баг `days_remaining` — исправлен (2026-09-02)
**Проблема:** `days_remaining` не включал сегодняшний день. В первый день периода возвращал 29 вместо 30, `dl_pred` = 5172 вместо 5000. Для period 20→19: 20-е = 29 вместо 30, 19-е работало корректно (=1).

**Решение:**
1. Ветка `start == 1`: `max(days_in_month - today.day + 1, 0)` — добавлено `+1`.
2. Ветка `today.day >= start`: `remaining + next_days + 1` — добавлено `+1`.
3. Ветка `today.day < start` (последний день) — корректна, не тронута.
4. Дубликат в `_finish_onboarding` (menu.py) исправлен идентично.
5. 14 тестов в `test_daily_limit_scenarios.py` — покрывают все 3 ветки + daily_limit + active_budget + _build_status.

**Продуктовое правило (зафиксировано тестами):** `days_remaining` включает сегодняшний день. Первый день периода = полное количество дней (30), последний день = 1. `daily_limit` = константа на весь период (не меняется от трат/даты). `dl_pred` = динамический лимит (пересчитывается после трат).

**Файлы:** `models.py:70,74`, `menu.py:814,817`, `tests/test_daily_limit_scenarios.py`

### Вечерний лимит — живой вместо планового + мешок в настройках (2026-09-02)
**Проблема:** вечерний отчёт показывал `budget.daily_limit` (плановый `income/total_days`, напр. 10000₽), а не `dl_pred` (живой с учётом трат, ~8000₽). Пользователь получал ложное чувство запаса. В настройках `•` выглядел как точка.

**Решение:** `finalize_evening_report` теперь вычисляет `limit = available_cash / days_left` (как `_build_status`). `_render_settings` → `💰 Доход/Свободно`.

**Файлы:** `evening_flow.py`, `menu.py`

### Категории и составные emoji (2026-09-02)
**Проблема:** `get_category_display` брал только первый codepoint (`unicodedata.category(name[0])=="So"`), ломая `🧒🏼` → `🧒 🏼детское` и `⚕️` → `⚕ ️ Здоровье`. `save_new_category` → `capitalize()` делал `🧒🏼Детское` → `🧒🏼детское`.

**Решение:** `helpers.py:260` `build_category_name(raw, fallback_emoji)` — `_extract_emoji` + один пробел + `text[:1].upper()+text[1:]` без `.lower()`. `categorization.py:258` `get_category_display` → через `_extract_emoji` (чинит старые записи без миграции).

**Файлы:** `helpers.py`, `categorization.py`, `categories.py`, `menu.py`

### День 4: B18 + ASAP-дубликат + E501 (2026-09-02)
**Проблема B18:** `morning_report.py:173` `money_for_life = budget.free_money - spent_period` — двойной вычет, `free_money` уже остаток. **ASAP:** `get_today_expenses_grouped` дублировал `Транспорт транспорт` когда `desc == cat_name`. **E501:** 18 строк >100 в `phrases.py`.

**Решение:** B18 → `budget.free_money`; ASAP → `desc.lower()==cat_name.lower()` → `prefix=emoji`; E501 — ручной перенос.

**Файлы:** `morning_report.py`, `expense_service.py`, `phrases.py`

### Категории и составные emoji (2026-09-02)
**Проблема:** `get_category_display` брал только первый codepoint (`unicodedata.category(name[0])=="So"`), ломая `🧒🏼` → `🧒 🏼детское` и `⚕️` → `⚕ ️ Здоровье`. `save_new_category` → `capitalize()` делал `🧒🏼Детское` → `🧒🏼детское`. Два пути создания давали разный стиль.

**Решение:** `helpers.py:260` `build_category_name(raw, fallback_emoji)` — `_extract_emoji` + один пробел + `text[:1].upper()+text[1:]` без `.lower()`. `categorization.py:258` `get_category_display` → через `_extract_emoji` (чинит старые записи без миграции). Оба хендлера используют helper.

**Файлы:** `helpers.py`, `categorization.py`, `categories.py`, `menu.py`

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

### Intercept reply-menu inside period FSM (2026-07-22)
**Проблема:** при нажатии reply-кнопки меню (Настройки, Статистика и т.д.) в состоянии `waiting_for_period_start` FSM-хендлер молча инкрементил `_retry_count` и после 3 попыток сбрасывал FSM, не показывая Cancel-кнопку пользователю.

**Решение:**
1. Добавлен `REPLY_MENU_COMMANDS` — `frozenset` из 5 reply-кнопок (`BTN_ADD_EXPENSE`, `BTN_DAILY_LIMIT`, `BTN_STATS`, `BTN_SETTINGS`, `BTN_HELP`).
2. Два хендлера-перехватчика (`BudgetSetup.waiting_for_period_start` и `EditBudget.waiting_for_period_start`) с фильтром `F.text.in_(REPLY_MENU_COMMANDS)` зарегистрированы **выше** основных хендлеров.
3. При перехвате: дружественное сообщение («Мы тут вообще-то период настраиваем…») + `get_cancel_keyboard()` — без инкремента `_retry_count`.
4. `_retry_count` растёт только на genuinely неверный ввод (не число, не команда меню).

### Monthly Summary + Smart Rollover (2026-07-22)
**Проблема:** `get_active_budget()` возвращает `None` на день после окончания периода (`period_end + 1`), потому что ни одно из двух условий поиска активного бюджета не совпадает. Код проверки саммари стоял ПОСЛЕ guard `if not budget: continue` → саммари никогда не отправлялся, утренние и вечерние отчёты навсегда замолкали. Отдельная проблема: кнопка «🚀 Запустить новый период» вела в полный BudgetSetup FSM с «Пропустить» на критических шагах → при пропуске дохода бюджет создавался с `period_start_day=1` (баг «9 дней»).

**Решение (Smart Rollover):**
1. Проверка завершившегося периода вынесена ДО active-budget guard в `send_morning_reports()`.
2. Monthly Summary отправляется через `send_rich_message()` **без кнопок** (чистый отчёт, остаётся в чате навсегда).
3. Следом отправляется отдельное сообщение-ролловер через `bot.send_message()`:
   ```
   🎯 План на новый период (с 20-го числа):
   На основе прошлых месяцев твой средний чек — X ₽.
   Оставляем доход Y ₽ и старые лимиты?
   ```
   С двумя кнопками: `[✅ Продлить план] [⚙️ Изменить]`.
4. **Fast Track** (`rollover_keep`): копирует все настройки из предыдущего бюджета (доход, дата, mandatory, кубышка, хотелка, округление) и создаёт новый бюджет в 1 клик. Ролловер-сообщение удаляется.
5. **Edit Path** (`rollover_edit`): новый `NewPeriodSetup` FSM (2 шага: доход + дата). Остальные настройки копируются из старого бюджета автоматически. Кнопки «📦 Оставить X» вместо «Пропустить».
6. Полностью удалён старый `start_new_period` хендлер и кнопка «🚀 Запустить новый период».
7. Добавлена тестовая команда `/test_monthly_summary`.

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

### B13 + B14: `free_money` не сбрасывался при ролловере + `spent_period` считал все траты (2026-07-22)
**Проблема (B13):** `save_budget()` не трогал `free_money`. После Fast Track / Edit Path старый `free_money` (из reconciliation) оставался и переопределял `daily_limit`.

**Решение:** `save_budget()` получила параметр `free_money: float = 0` — теперь `free_money` явно обнуляется при создании или обновлении любого бюджета. Один SQL-запрос, без дополнительного roundtrip.

**Проблема (B14):** `_build_status()` считал `spent_period` как `SUM(Expense.amount) WHERE is_deleted == False` без фильтра по дате — суммировались все траты за всё время, затем вычитались из `free_money` или `income`, давая бессмысленный остаток.

**Решение:** SQL-запрос `spent_period` теперь фильтруется по `Expense.date >= period_start AND Expense.date < next_day_after_end`, где границы вычисляются через `get_period_dates(budget)`. `next_day = period_end + timedelta(days=1)` гарантирует, что последний день периода покрывается до 23:59:59.

### B18: `_build_status` — двойной вычет `spent_period` при `free_money > 0` (2026-07-22)
**Проблема:** `money_for_life = budget.free_money - spent_period`. `free_money` — это остаток на карте, введённый через reconciliation (кнопка «Остаток на карте»). Все прошлые траты периода уже учтены в этом остатке (деньги физически ушли с карты). Вычитание `spent_period` ещё раз давало заниженный «Остаток на жизнь» в статусе (напр. 262 100₽ вместо 275 000₽). `daily_limit` при этом считался верно (делил `free_money`, не `money_for_life`).

**Решение:** `money_for_life = budget.free_money` — без вычитания `spent_period`.

### B19: Retry+cancel везде, где FSM-ввод числа (2026-07-22)
**Проблема:** 7 FSM-хендлеров числового ввода не имели retry-счётчика (3 попытки → выход) и кнопки «Отмена» — пользователь мог бесконечно получать «❌ Введи число» без выхода. Ещё 3 хендлера имели retry, но без cancel-кнопки на сообщении об ошибке.

**Исправленные хендлеры:**
- `process_income` (BudgetSetup.waiting_for_income)
- `process_mandatory` (BudgetSetup.waiting_for_mandatory)
- `process_black_day` (BudgetSetup.waiting_for_black_day)
- `save_recalc_balance` (EditBudget.waiting_for_recalc_balance)
- `save_add_income` (EditBudget.waiting_for_add_income)
- `save_mandatory` (EditBudget.waiting_for_mandatory)
- `save_black_day` (EditBudget.waiting_for_black_day)
- `process_expense` (AddExpense.waiting_for_amount) — добавлена cancel-кнопка
- `save_edit_expense` (EditExpense.waiting_for_amount, history.py) — добавлена cancel-кнопка
- `handle_evening_expense` (EveningState.filling, evening_flow.py) — добавлены retry+cancel

**Паттерн:** `check_retry()` + `get_cancel_keyboard()` + `ERR_TOO_MANY_RETRIES` на 3-й попытке.

---

### B19: retry+cancel — единая функция + blockquote-цитата трат (2026-07-22)
**Рефакторинг retry:** 10 идентичных блоков `check_retry`+`get_cancel_keyboard`
вынесены в `handle_invalid_input()` в `_shared.py`. Все 13 мест (menu.py 10,
history.py 1, evening_flow.py 2) теперь вызывают её одной строкой.

**Blockquote для трат:** строка «Остаток» в статусе теперь оборачивает
сегодняшние траты в `<blockquote>` — цветной отступ слева (Telegram HTML).
Для защиты от XSS `cat_name` и `description` обёрнуты в `safe()`.

**Исправлено:**
- `expense_service.py`: `safe()` импорт + `safe(cat_name)`
- `_build_status`: `<blockquote>` вокруг expense_lines
- `_shared.py`: единый `handle_invalid_input()`

### Recovery v1-infra (2026-09-05) — kill-switch off
**Проблема:** нужен временный режим поверх `Budget.daily_limit` для возврата к замороженному `B` без изменения бюджета, с выбором 60/70/80% и вечерним пересчётом длительности.
**Решение:**
- `Budget.base_daily_limit` frozen при `save_budget()`/`resolve_frozen_baseline()` (атомарно `WHERE base_daily_limit IS NULL`), `recovery_states` (история, `initial_*` immutable, `total_days` mutable) + `recovery_offer_state` (`dismissed/last_offer_at/deficit`), миграция `database.py` (`ALLOWED_TABLES/COLUMNS`, SQLite `REAL`/`INTEGER` vs PostgreSQL `NUMERIC`/`BOOLEAN`).
- `recovery_service.py` чистая математика `Decimal`: `trigger 0.85, fast 0.60/balanced 0.70/soft 0.80, success 0.90, replan 0.90, small 1.10, tail 7, cooldown 3, min 1000` + `calculate_recovery_options/days, should_offer, check_success, is_small_overspend, should_repeat_offer` + DB-helpers `get_active_recovery/create_recovery/stop/complete/update_days/expire` (все `get_msk_now()` tz-aware, `UPSERT` offer).
- Оркестрация за `RECOVERY_ENABLED=false`: `menu.py:_build_status` рендер (скрытие нулевых резервов, `🧘 день 3 из 10 / 7000·10дн / После этого — 10000 ещё 7дн`), коллбэки `recovery:choose:fast|balanced|soft` (re-validate `B*days- money`, `days+7<=remaining`), `dismiss/stop/show_options`, бюджет-хуки `add_income/recalc/mandatory/black_day/period_start` (не `saving_today`, отдельный flow), `morning_report` (active/success/offer), `evening_report` (факт `saving_today=max(0,target-spent)`, `10→8` честно, прогноз только `+`), `rollover` + `period_end` → `expired(period_end)`.
- `phrases.py` 16 групп (`BTN_RECOVERY_*`, `RECOVERY_*`), `keyboards.py` 3 клавиатуры, `get_user_now()` обёртка, `pyproject.toml` `ignore E712`.
**Файлы:** `models.py:58,159`, `database.py:13,204`, `config.py:18`, `helpers.py:224`, `recovery_service.py`, `budget_service.py:36`, `menu.py:76,590,854`, `keyboards.py:233`, `morning_report.py:343`, `evening_report.py:240`, `phrases.py:664`.
**P1a-c:** `phrases.py:762,788,806` — `STATUS_*`/`MORNING_*`/`ROLLOVER_*` 45 ключей → `menu.py` статусы/ролловер/настройки полностью на `phrases.*` (`ade2696`, `efb058e`, `8fd4f45`).

### ADR: Recovery≠Recalc≠Savings (2026-09-07) — hard clean Кубышки
**Фиксация:** `Recalculate` (`free_money`, источник истины, `budget_service.py:167`) ≠ `Recovery` (временный `target/total_days`, не меняет `Budget.daily_limit/free_money/base_daily_limit`, `recovery_service.py:204`) ≠ `Savings/Cubby deleted` (1 юзер, `black_day_fund` deprecated).
**Поток:** `Fact → Recalc? (сколько реально денег) → Recovery? (временный план возможен? `days+7<=remaining`, `trigger 0.85`) → Normal`. `RECOVERY_ENABLED` — kill-switch, не бизнес-if: Recovery-aware morning/status имеют приоритет над legacy `simulated/cubby` (не `if enabled: suppress`).
**Правила:** `recalc` после `apply_reconciliation` обязан вызвать `_handle_recovery_budget_change` `menu.py:98` → `complete` при `dl_pred>=0.90*B` или `shortened` при `new_days<old`; `dismissed` инвалидируется при `deficit≥0.5*B` / 3д / новый период, не при каждом `completed`; `tail=7` объяснить один раз `→ потом {baseline} ещё {tail}, чтобы оставить запас`; `NO_VALID_OPTIONS_TAIL` — только в telemetry. Кубышка: 15 фраз + 5 кнопок + 8 веток `morning_report.py:185`/`menu.py:527` удалены, БД `black_day_fund` nullable без дропа.

### ADR-2: Zone=состояние, Recovery=действие (2026-09-07) — без кода
**Фиксация без пуша:** зоны и код `pct>80 🟢/>=51 🔵/>=26 🟡/<26 🔴` `menu.py:546`/`morning_report.py:214` остаются без изменений. При `Recovery offer/active` `menu.py:611`/`morning_report.py:369` zone footer не показывается, вместо него Recovery footer `phrases.py:693,698`. Zone label всегда по `pct`, не зависит от Recovery. После `finished` — обычный footer. Только 1 фраза меняется: `RECOVERY_DAILY_OFFER` `phrases.py:698` `💡 Можно вернуть обычный лимит` → `💡 Есть варианты восстановить лимит. Сейчас: {dl_pred} ₽/день. Разрулим, бро.` План, не код.

## 📌 Feature Flags

| Флаг | По умолчанию | Что контролирует |
|------|-------------|------------------|
| `EXPENSE_SIMPLE_CHECK` | `True` | `True` → ReplyKeyboard (persistent menu внизу чата), inline-меню скрыто, чеки трат без лишних кнопок. `False` → inline-клавиатуры, кнопка «В главное меню» в отчётах. |
| `RECOVERY_ENABLED` | `False` | Kill-switch Recovery. `False` → инфра дормантна (миграция есть, UI скрыт). `True` → активны Daily Limit блок, утреннее предложение, вечерний пересчёт `total_days`, бюджет-хуки. |
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

### is_active=NULL на PostgreSQL: новый пользователь не создавался (2026-09-01) — ⚠️ Устарело `06082b2`
**Симптом (2026-09-01):** новый пользователь нажимал `/start` — бот молчал. Railway-логи: `IntegrityError: null value in column "is_active" of relation "users" violates not-null constraint`.

**Корень (2026-09-01):** `get_or_create_user()` создавал `User(...)` без поля `is_active`. На SQLite (dev) NOT NULL с дефолтом `True` работает, на PostgreSQL (prod) — жёсткое падение. Плюс в проекте не было `@dp.errors()` handler → исключение глоталось молча.

**Решение (2026-09-01):**
1. `user_service.py`: `User(..., is_active=True)` — явно задаём значение.
2. `main.py`: добавлен `@dp.errors()` handler — ловит все необработанные исключения, логирует traceback, отправляет пользователю `ERR_GENERIC`.
3. Новая фраза `ERR_GENERIC` в phrases.py.

**Update 06082b2 (2026-09-09) — B, dead field:** `User.is_active` удалён из `models.py:35` ещё `0a89bf9 2026-06-03` (мертвое поле, `Wishlist.is_active` не трогаем). `user_service.py:12` `is_active=True` давал `TypeError` на новых юзерах (`385325447 219ms`). Фикс `06082b2` `User(...)` без `is_active`, legacy-колонка в PG остаётся deprecated, `PRD User.is_active` — legacy. Snapshot/B2/Recovery не трогали.

### Вечерний FSM: мультилайн-парсинг (2026-08-25)
**Проблема:** в вечерней сессии (22:00) использовался однострочный `parse_expense_text()` вместо мультистрокового `parse_multi_expense_text()`. При вводе «1700 аптека\n3500 кафе\n1256 лавка» первая сумма парсилась, остальное уходило в описание одной траты.

**Решение:** evening_flow.py переведён на `parse_multi_expense_text()` — каждая строка парсится как отдельная трата, все добавляются в контейнер.

### Живой дневной лимит: dl_base → dl_pred в UI (2026-08-25)
**Проблема:** в статусе и утреннем отчёте `dl_base` (budget.daily_limit) показывался как «Лимит N₽/день» — константа `income / period_total_days`, не зависящая от фактических трат. При перерасходе лимит не уменьшался, вводя пользователя в заблуждение.

**Решение:**
1. В `_build_status` (menu.py): «Лимит N ₽/день», «Свободно X₽» и ⚠️-предупреждение — замена `dl_base` → `dl_pred = money_for_life / days_remaining`.
2. В `send_morning_reports` (morning_report.py): вчерашние траты теперь сравниваются с `dl_pred`; добавлена новая строка «📋 План на сегодня: N ₽/день».
3. Новая фраза `MORNING_TODAY_PLAN` в phrases.py.
4. **Не затронуто:** зоновые расчёты (`pct_pred`, `pct_sim`), модель `Budget.daily_limit`, reply-кнопка «Дневной лимит» (осталась статичной — ограничение Telegram).

**Известная несостыковка (B18 в morning_report.py):** `money_for_life` в утреннем отчёте при `free_money > 0` вычитает `spent_period` (morning_report.py:156), тогда как в статусе (menu.py:388) — нет. Фикс B18 долетел до menu.py, но не до morning_report.py. Следующим шагом — синхронизировать.

### 🔴 ASAP: Дублирование названия категории в трате (2026-07-22)
**Симптом:** запись «83 транспорт» сохраняется, но в статусе отображается как «🚌 Транспорт транспорт — 83₽» — название категории повторяется дважды.

**Корень:** `detect_category_db()` по описанию находит категорию «Транспорт» (эмодзи 🚌). При форматировании строки в `get_today_expenses_grouped` (expense_service.py:318) префикс категории содержит `emoji + cat_name`, а описание (`desc`) тоже совпадает с `cat_name` → «Транспорт транспорт».

**Нужно:** либо не дублировать описание, если оно совпадает с именем категории, либо убрать `cat_name` из префикса, если описание уже содержит его.

**Связано:** эмодзи в итоговых отчётах (Monthly Summary) отображаются криво — в одних местах есть, в других нет. Единый формат отображения категории с эмодзи.

### 🔴 B1: recalc→Recovery не предложился (2026-09-07) — ✅ Починено
**Симптом:** `RECOVERY_ENABLED=true`, `101617 → 7816 ₽/день (B=10000, 13 дн.)` `reconcile` `menu.py:1966` → статус `🟢 В лимите ... Всё пучком` без Recovery, в `23:30` Recovery появился (`🧘 день 1 из 5`). **Корень:** `_handle_recovery_budget_change` `menu.py:98` не создаёт offer; `should_repeat_offer` `recovery_service.py:146` подавлен `dismissed=true`. **Решение (2026-09-07):** `recovery_service.py:203` `invalidate_recovery_offer_context` `dismissed=false/last=None` при любом `recalc` `menu.py:1966` (новая реальность), пассивно — следующий `_build_status` `menu.py:611` покажет `RECOVERY_DAILY_OFFER` `phrases.py:698`.

### 🔴 B2: вечер 22:00 `Посмотреть отчёт` молчит (2026-09-07) — ✅ Починено
**Симптом:** `22:00` `EveningState.filling` кнопка `show_report` молчит, `23:30` работает. **Корень:** `evening_flow.py:125` `@callback + EveningState.filling` требовал `state==filling`, при рестарте `state=None` → игнор. **Решение (2026-09-07):** `evening_flow.py:125` фильтр снят, внутри `get_state()` + `is_filling` fallback + stale `msg_date != today` → молча `edit_reply_markup(None)` без отчёта, `try/except/finally always callback.answer()` + `ERR_REPORT_FAILED` `phrases.py:62`.

### 🔴 B3: Остановить восстановление остаётся (2026-09-07) — ✅ Починено
**Симптом:** `RECOVERY_ENABLED=true` `08:00` `msg_A` с `⏹ Остановить восстановление` `phrases.py:674` затиралось `msg_B` Статуса, `KeyboardCleanupMiddleware` `middleware.py:22` `pop` 1 слот чистил только `B`, `A` оставалось с кнопкой. **Корень:** `_last_keyboard: dict[int,int]` 1 слот + гонка 2 сообщений. **Решение (2026-09-07):** `middleware.py:19` `dict[int,set[int]]` до 5 + `Lock per chat` `_get_lock`, `AutoTrack` `middleware.py:55` `add` под `Lock` с лимитом 5, `rich_api.py:34` `discard` вместо `pop`, `Cleanup` `middleware.py:22` `for mid in mids: edit` — чистит все до 5, гонка под `Lock` не теряет `set`.

### 🔴 B4: Остаток/Лимит не меняется после recalc (2026-09-07) — ✅ Починено одним коммитом
**Симптом:** после `recalc 101617 → 7816` `Остаток 101617/Лимит 9237` застыли, хотя `Свободно 8397→7997→4297` падало, `Потрачено 840→4940` росло, `evening_flow` минус `period_spent` дважды. **Корень:** `Budget.free_money` `models.py:57` snapshot без `spent_at_recalc`, `_build_status` `menu.py:525` `money=free` без `- (spent - spent_at)` + `evening_flow.py:142` двойной `- period_spent` + `Recovery 0.90` `recovery_service.py:114`. **Решение (2026-09-07):** `models.py:57` `spent_at_recalc Float 0` + `database.py:13,184` миграция, `budget_service.py:189` `apply_reconciliation` атомарно `free+spent_at`, `_current_money_for_life` `free - max(spent - spent_at,0)` — единая `max(...,0)` в `menu.py:525,morning_report.py:145,evening_flow.py:142,evening_report.py:239,menu.py:763,854,949`, `evening_flow` без двойного минуса, `recovery_service.py:114` `check_success 0.90→1.00`, `menu.py:580` `Дневной лимит Recovery` `if active: Лимит на сегодня: target 6000, Свободно=max(target-spent,0) 950` порядок `БАЛАНС/Сегодня/🧘/Лимит/Свободно/После 10000/Период Прогноз 8468` + `footer` `Идём по плану 👍` при `offer/active`.

### 🔴 B4.1: Snapshot-канон (основательный, без костыля) (2026-09-09) — ✅ Починено поверх B4 + c5cb187 отката
**Симптом:** `c5cb187` откатил `menu.py:522` к `money=free` без `spent_at` → `Остаток 101617` снова застыл (`97917` ожид.), `evening_flow` дубль `if free>0`, 6× `getattr(budget,"spent_at_recalc",0)`, `black_day` в live-ветке, 3 источника границ периода (`get_period_dates` vs `get_current_period_expenses_sum(today)` vs `days_remaining 30`). **Решение (2026-09-09):** `budget_service.py:192` `get_money_for_life`/`get_daily_pred`/`get_period_spent` — единственные, `spent_at=float(budget.spent_at_recalc or 0)` без `getattr`, `black_day` исключён из live, `get_period_dates` полуинтервал `[period_start, next_day)` — единственный для `spent_period`. `menu.py:97/486/765/844/930` `_build_status/_handle_recovery/choose/dismiss/show_options` → канон, `_build_status 652` дубль fetch схлопнут в reuse `_recovery_active/_recovery_offer`. `evening_flow.py:157` дубль схлопнут `money+get_daily_pred`, `morning_report:149`/`evening_report:228` через канон, `evening_report 229` `timedelta` import. `reconcile`→preview, `apply`→commit `free+spent_at` invariants. Сценарии `101617-(1540-1240)=101317` / `101617-(4940-1240)=97917` закреплены.

### 🔴 B4.2: `save_budget` сбрасывал `spent_at` (2026-09-09) — ✅ Защита `39efc3d`
**Симптом:** после `Recalc B` `free 101617` `spent_at 0` (`65 rows` `192546` → `БАЛАНС 0`), старый `spent_at 1240` невосстановим, `save_budget:96` на `UPDATE` обнулял `spent_at_recalc` — любой `rollover/mandatory` уничтожал новый снапшот `free+spent_at=192546` после `Recalc B`. **Решение:** `budget_service.py:96` удалить строку `budget.spent_at_recalc = 0` в ветке `if budget:` (оставить `109` `default 0` только на `INSERT` нового месяца). `apply_reconciliation:281` атомарно `free=X`, `spent_at=192546` → `money=X - max(spent-192546,0)=X`. Исторический `1240` не бэкфиллим, `16cfe3a` канон не трогаем. `ruff F passed`, `pytest 357 passed`.

### 📝 B5.1: Вечер — итоговая таблица (2026-09-11) — ✅ `Evening` канон
**Симптом:** 10 фраз `ZERO 3/GREEN 4/OVER 3` + `AUTO_CLOSE 5` без градаций `0.5×/2×/3×`, `Хотелка/Кубышка` `GREEN_1/3`, `frugal/аудит/гречка` пафос. **Решение:** `phrases.py:293-420` `INITIAL/CONTAINER/TIMEOUT` упрощены `👁 День подошёл…`/`Вот что набралось…`/`⏱ Время вышло…`, `ZERO_1-3` `Бро сегодня ни одной траты…`, `GREEN_1` strong `<0.5×` `machine {saved}`, `GREEN_2-4` ordinary `0.5×≤spent≤limit`, `OVER_1-2` ordinary `limit<spent≤2×`, `OVER_3` strong `2×<spent≤3×`, `SPECIAL 🛌` `>3×`, `AUTO_CLOSE 5→4` `Полночь близко/День закрыт`. `evening_report.py:49` 6 веток `spent==0 / <0.5*limit / ≤limit / ≤2*limit / ≤3*limit / >3*limit` (сильные 1/1, обычные random). `ruff F passed`, `pytest 357 passed`.
