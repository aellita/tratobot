# SESSION_PLAN.md — План сессии на 2 недели

> Статус в начале файла. Обновляй в конце каждой сессии: что сделано, что дальше.

---

## 📊 Статус

| Статус | Кол-во задач |
|--------|:------------:|
| ✅ Готово | 42 |
| 🔧 В работе | 0 |
| ⏳ Ожидает | 2 |

**Следующая задача:** День 5 — Dogfooding Recovery (включить `RECOVERY_ENABLED=true`) → фразы 3–5 вариантов

---

## Неделя 1 — Product Cleanup

### День 1: Новый онбординг (2 шага)

> **Цель:** `/start` → доход → период → готово. Кнопка «Пропустить» на шаге дохода убрана.

- [x] ✅ `menu.py:215` — шаг `waiting_for_income`: клавиатура только `[⬅️ Отмена]`, без `⏭️ Пропустить`
- [x] ✅ `menu.py:661-665` — `skip_step` → убрать ветку `waiting_for_income`
- [x] ✅ `menu.py:667` — `skip_step` → `waiting_for_period_start` → `_finish_onboarding`
- [x] ✅ `menu.py:863` — выбор дня (кнопка) → `_finish_onboarding` вместо `set_state(waiting_for_mandatory)`
- [x] ✅ `menu.py:907` — ввод дня (текст) → `_finish_onboarding` вместо `set_state(waiting_for_mandatory)`
- [x] ✅ `phrases.py` — `ONBOARDING_HINT_SETTINGS` + slim-формат в `_finish_onboarding`
- [x] ✅ `test_onboarding_fsm.py` — поправлены переходы, убраны недостижимые skip-тесты
- [x] ✅ `ruff check` + `ruff format` — без новых ошибок

---

### День 2: Продуктовые упрощения (3 задачи)

#### Задача 3 (сделана первой): Удаление округления

> **Цель:** округление трат отключено — сумма сохраняется как есть, без ROUND_UP и add_spare_change_to_goal.

- [x] ✅ `menu.py:33-42` — убраны импорты `compute_rounding`, `get_rounding_mode`, `add_spare_change_to_goal`
- [x] ✅ `menu.py:1147-1230` — `_save_expenses_from_parsed_list`: без `rounding_mode`, без `total_spare`, `effective = amount`
- [x] ✅ `menu.py:1291-1320` — `process_expense`: без блока ROUND_UP
- [x] ✅ `menu.py:2098-2125` — `handle_text`: без блока ROUND_UP
- [x] ✅ `menu.py:1694-1705` — `menu_settings`: убрана строка «Округление»
- [x] ✅ `ruff check` + `ruff format` — без новых ошибок

#### Задача 1: Настройки → Дополнительное планирование

> **Цель:** обязательные/кубышка/хотелка убраны из главного экрана настроек в подменю. Паттерн `_from_advanced_planning: set[int]` (аналог `_cat_back_target`).

- [x] ✅ `keyboards.py` — `get_settings_keyboard()`: 4 кнопки вместо 7
- [x] ✅ `keyboards.py` — новая `get_advanced_planning_keyboard()`
- [x] ✅ `menu.py` — `_from_advanced_planning: set[int]` + хендлер `menu_advanced_planning`
- [x] ✅ `menu.py` — callback-обёртки `adv_mandatory` / `adv_black_day` / `adv_wishlist`
- [x] ✅ `menu.py` — `_render_settings` + `_render_advanced_planning` (единые хелперы)
- [x] ✅ `menu.py` — `menu_settings` + handler `BTN_SETTINGS`: текст доход + период (согласованы)
- [x] ✅ `menu.py` — `save_mandatory`/`save_black_day`/`save_wishlist`: проверка `_from_advanced_planning`
- [x] ✅ `phrases.py` — `BTN_ADVANCED_PLANNING`
- [x] ✅ `tests/test_settings_keyboard.py` — 5 тестов на кнопки

#### Задача 2: Rollover-защита

> **Цель:** предупредить о переносе обязательных/кубышки при продлении периода.

- [x] ✅ `menu.py:304-310` — значения сохранены до `save_budget`
- [x] ✅ `menu.py:335-348` — динамический список `carried_parts` (Обязательные/Кубышка/Хотелка с `safe()`)
- [x] ✅ `menu.py:350-357` — новый текст «Перенесено из прошлого периода» или `ROLLOVER_CONFIRMED`
- [x] ✅ `menu.py:359` — `edit_text()` вместо `delete()` (Message Lifecycle Policy)
- [x] ✅ `menu.py:1694` — `<blockquote>` в `_render_settings`

**Формат сообщения:**
```
✅ План продлён.

📋 Перенесено из прошлого периода:
• Обязательные: 40,000₽
• Кубышка: 10,000₽
• PS5: 80,000₽

💰 Дневной лимит: 3,666₽. Поехали. 🚀
```

---

### День 3: Проверить daily_limit

> **Цель:** убедиться, что формула корректна. Обнаружен и исправлен баг `days_remaining` (не включал сегодняшний день).

- [x] ✅ Обнаружен баг: `days_remaining` не включал сегодняшний день (29 вместо 30)
- [x] ✅ `models.py:70,74` — `days_remaining`: `+1` в ветках `start==1` и `today.day>=start`
- [x] ✅ `menu.py:814,817` — дубликат в `_finish_onboarding`: те же `+1`
- [x] ✅ Ветка `today.day < start` (последний день = 1) — корректна, не тронута
- [x] ✅ Новый файл `tests/test_daily_limit_scenarios.py` — 14 тестов (6 days_remaining + 5 daily_limit + 1 active_budget + 2 _build_status)
- [x] ✅ Полный прогон: 357 passed — регрессий нет
- [x] ✅ `ruff check` + `ruff format`

**Продуктовое правило (зафиксировано):**
- `days_remaining` включает сегодняшний день
- Первый день периода = полное количество дней (30)
- Последний день = 1
- Для периода 20→19: 20-е = 30, 19-е = 1
- `daily_limit` = доступные деньги / дней всего периода (константа, не меняется от трат)
- `dl_pred` = деньги для жизни / оставшиеся дни (пересчитывается после трат)

---

### Фикс по фидбеку (вечерний итог + настройки)

- [x] ✅ `menu.py:_render_settings` — `•` → `💰` (Доход/Свободно)
- [x] ✅ `evening_flow.py:finalize_evening_report` — лимит теперь `dl_pred` (live), не `budget.daily_limit` (плановый)

### Фикс: категории и составные emoji (2026-09-02)

> **Цель:** исправить отображение составных emoji (🧒🏼/⚕️) и единый стиль создания/переименования.

- [x] ✅ `helpers.py:260` — новый `build_category_name(raw, fallback_emoji)` (один пробел, `text[:1].upper()+text[1:]` без `.lower()`)
- [x] ✅ `categorization.py:258` — `get_category_display` → через `_extract_emoji` (чинит `🧒 🏼детское`/`⚕ ️ Здоровье` без миграции)
- [x] ✅ `categories.py:223` — `process_cat_rename` → `build_category_name`
- [x] ✅ `menu.py:1497` — `save_new_category` → `build_category_name` (был `capitalize()`)
- [x] ✅ `ruff format` + `pytest` — 33 passed

### День 4: B18 + ASAP-дубликат + E501

> **Цель:** закрыть технический хвост.

- [x] ✅ B18: `morning_report.py:173` — `budget.free_money - spent_period` → `budget.free_money`
- [x] ✅ ASAP-дубликат: `expense_service.py:313` — если `desc.lower() == cat_name.lower()` → `prefix = emoji`
- [x] ✅ E501: `phrases.py` — 18 строк разбиты вручную, `ruff format`
- [x] ✅ `ruff check` + `ruff format`
- [x] ✅ `pytest` — 357 passed

### День 4.5: Recovery v1-infra (kill-switch off)

> **Цель:** временный режим поверх `Budget.daily_limit` — `B` frozen, 60/70/80%, `+7`, `85/90/110`, `get_user_now` tz-aware. Review: `datetime.now()` → `get_msk_now()`.

- [x] ✅ `models.py:58` — `Budget.base_daily_limit` nullable Float (frozen B)
- [x] ✅ `models.py:159,181` — `RecoveryState` (`recovery_states`) + `RecoveryOfferState` (`recovery_offer_state`) + `_get_user_now` wrappers
- [x] ✅ `database.py:13,204` — `ALLOWED_TABLES/COLUMNS` + миграция `base_daily_limit` + `CREATE TABLE IF NOT EXISTS` (SQLite/PostgreSQL)
- [x] ✅ `config.py:18` — `RECOVERY_ENABLED=false` + 10 констант `TRIGGER 0.85, FAST 0.60...`
- [x] ✅ `helpers.py:224` — `get_user_now/get_user_now_aware` (MSK сейчас, интерфейс для EKB)
- [x] ✅ `recovery_service.py` — чистая математика `Decimal` + DB-helpers (`get_active_recovery/create/stop/complete/update/expire`, `dismiss_offer`) — все `get_msk_now()`
- [x] ✅ `budget_service.py:36` — `resolve_frozen_baseline()` + `save_budget()` фризит `B` (`WHERE base_daily_limit IS NULL`)
- [x] ✅ `phrases.py:664` — 16 групп `BTN_RECOVERY_*/RECOVERY_*` + `ERR_ROLLOVER_NOT_FOUND/ROLLOVER_ASK_INCOME`
- [x] ✅ `keyboards.py:233` — `get_recovery_offer/single/active/plan_keyboard` (`fast|balanced|soft`)
- [x] ✅ `menu.py:76,590,854` — `_build_status` рендер (скрытие нулевых резервов, `🧘 день 3 из 10`), коллбэки `recovery:show_options/choose/dismiss/stop` с re-validate `days+7<=remaining` + бюджет-хуки `_handle_recovery_budget_change` + `rollover` expire `period_end`
- [x] ✅ `morning_report.py:343` — active/success/offer ветки за флагом, `evening_report.py:240` — вечерний пересчёт `total_days` (`10→8` честно) + прогноз только `+`, 0 кнопок
- [x] ✅ `pyproject.toml` — `ignore E712` (SQLAlchemy `== False`)
- [x] ✅ `ruff` + `pytest 357 passed` — Review: `datetime.now()→get_msk_now()` fixed, safe to push

### P0: Morning phrases extraction (hardcode → phrases.py)

> **Цель:** убрать `TODO: extract` в `morning_report.py` — все утренние строки через `phrases.py`.

- [x] ✅ `phrases.py:347` — `MORNING_YELLOW_SIM_GREEN_1/2`, `MORNING_YELLOW_SIM_BLUE_1/2`, `MORNING_YELLOW_SIM_NONE_1/2`, `MORNING_RED_SIM_GREEN_1/2`, `MORNING_RED_SIM_BLUE_1/2`, `MORNING_RED_SIM_YELLOW_1/2`, `MORNING_RED_DEAD_1/2` (14 ключей)
- [x] ✅ `morning_report.py:281` — `TODO` блоки → `phrases.MORNING_*` (7 веток `YELLOW_SIM_GREEN/BLUE/NONE`, `RED_SIM_GREEN/BLUE/YELLOW`, `RED_DEAD`)
- [x] ✅ Review P0: PASS — no hardcoded Russian, no SQLi, no lifecycle violations
- [x] ✅ `ruff format` + `pytest 357 passed`

### P1a: Menu status → phrases (zone, remaining, rollover, footers green/yellow-light)

> **Цель:** вынести статус-шапку и зелёные/жёлтые-light футовки в `phrases.py`.

- [x] ✅ `phrases.py:762` — `ROLLOVER_WITH_DETAILS`, `STATUS_ZONE_*` (6), `STATUS_REMAINING_*` (3), `STATUS_RESERVES_HEADER/BALANCE/TODAY/PERIOD`, `STATUS_FOOTER_END_*` (6), `GREEN_*` (3), `YELLOW_LIGHT_*` (3), `SETTINGS_*` (4), `ADVANCED_PLANNING_TITLE`, `ONBOARDING_INCOME_ACCEPTED` — 20 ключей
- [x] ✅ `menu.py:430,541,564,580,590,645,664,673,677` — rollover, zone_label, today/spent, reserves, BALANCE шаблон, footers `END_EMPTY/OK` + `GREEN` + `YELLOW_LIGHT` → `phrases.*`
- [x] ✅ Review P1a: PASS шапка, REQUEST CHANGES — остались cubby-футовки
- [x] ✅ `ade2696` → push

### P1b: Menu cubby footers + settings titles → phrases

> **Цель:** добить жёлтые/красные с кубышкой и настройки.

- [x] ✅ `phrases.py:788` — `STATUS_FOOTER_YELLOW_CUBBY_GREEN/BLUE`, `YELLOW_NONE_1-3`, `RED_CUBBY_GREEN/BLUE/YELLOW`, `RED_DEAD_1-3`, `ROLLOVER_KEEP_DATE_PROMPT` — 11 ключей
- [x] ✅ `menu.py:682,2147,2162,1295,1477` — `YELLOW_CUBBY_*`, `RED_CUBBY_*`, `RED_DEAD`, `_render_settings` (`PERIOD_FROM/WHOLE`, `MONEY_FREE/INCOME`, `BUDGET_TITLE`), `_render_advanced_planning`, `ONBOARDING_INCOME_ACCEPTED`, `ROLLOVER_KEEP_DATE_PROMPT` → `phrases.*`
- [x] ✅ `efb058e` → push

### P1c: Menu reserves/budgetComplete → phrases

> **Цель:** добить последние 5 хардкодов статуса.

- [x] ✅ `phrases.py:806` — `ROLLOVER_CARRIED_MANDATORY/SAVINGS/WISHLIST`, `STATUS_RESERVE_MANDATORY/SAVINGS/WISHLIST`, `STATUS_BUDGET_COMPLETE`, `WISHLIST_SAVED`, `BALANCE_UNKNOWN`, `PERIOD_DAY_SUFFIX`
- [x] ✅ `menu.py:431,538,577,1252,2388,2468` — carried/reserve bullets, `period_end_str`, `_finish_onboarding` `Готово!`, `save_wishlist`, `balance="неизвестно"` → `phrases.*` + fix `F841` spent_today
- [x] ✅ Review P1c: ✅ Чисто, `8fd4f45` → push

### P2: Monthly/budget → phrases (MONTHLY_*, DEFAULT_*)

> **Цель:** перенести оставшиеся 24 хардкода monthly/budget в `phrases.py` — 1 комит.

- [x] ✅ `phrases.py:762` — `MONTHLY_NO_CATEGORY`, `MONTHLY_NO_DATA`, `MONTHLY_ZONE_*` (4), `MONTHLY_TOTAL_SPENT/BUDGET_LABEL`, `MONTHLY_TOP_HEADER`, `MONTHLY_TABLE_*` (4), `MONTHLY_TOTAL_LABEL`, `MONTHLY_ROUNDING_LABEL`, `MONTHLY_PERIOD_LABEL`, `MONTHLY_DETAILS_SUMMARY` — 16 ключей
- [x] ✅ `monthly_report.py:150,213,239,241,262,271,280,289,320` — `Без категории`, зоны, `Итог за/в процессе`, `Всего потрачено/Бюджет/Топ`, `Прочее`, `Итого`, `Округления`, `Период/Детали` → `phrases.*`
- [x] ✅ `budget_service.py:91,103` + `goal_service.py:49` + `expense_service.py:321` + `category_service.py:66` — `"Хотелка"/"Прочее"` → `DEFAULT_WISHLIST_NAME`/`DEFAULT_CATEGORY`
- [x] ✅ Review P2: ✅ Чисто, `b125fa1` → push

---

### День 5: Dogfooding

> **Цель:** пройти полный цикл пользователем. Код не писать.

- [ ] ⏳ Новый пользователь → `/start` → доход → период → финал
- [ ] ⏳ Добавить трату → статус → ещё трату → статус
- [ ] ⏳ Настройки → Доп. планирование → задать обязательные
- [ ] ⏳ Статус с обязательными (проверить пересчёт лимита)
- [ ] ⏳ Новый период → ролловер → проверить перенос обязательных
- [ ] ⏳ Записать найденные баги/неудобства

---

## Неделя 2 — AI Insight

### День 6: WeeklyStats + агрегация

> **Цель:** новый сервис для сбора недельной статистики.

- [ ] ⏳ `src/services/weekly_insights.py` — dataclass `WeeklyStats`
- [ ] ⏳ `aggregate_weekly_stats(user_id) → WeeklyStats`
- [ ] ⏳ `build_deterministic_summary(stats) → str`
- [ ] ⏳ `build_weekly_prompt(stats) → str`
- [ ] ⏳ `ruff check` + `ruff format`

---

### День 7: Детерминированная сводка (без LLM)

> **Цель:** работающий вывод недельной статистики без AI.

- [ ] ⏳ Форматирование: total_spent, daily_average, top_categories, change_percent
- [ ] ⏳ Правила «мало данных»: нет предыдущей недели → без сравнения; days<3 → мягкое сообщение
- [ ] ⏳ `phrases.py` — строки для сводки
- [ ] ⏳ `ruff check` + `ruff format`

---

### День 8: LLM adapter

> **Цель:** Python считает, LLM формулирует.

- [ ] ⏳ `generate_insight(user_id) → str` — основной метод
- [ ] ⏳ `call_llm(prompt) → str` — вызов API (DeepSeek/OpenAI)
- [ ] ⏳ `config.py` — `LLM_API_KEY`, `LLM_MODEL`, `WEEKLY_INSIGHT_ENABLED=false`
- [ ] ⏳ Fallback: ошибка API → deterministic summary
- [ ] ⏳ `ruff check` + `ruff format`

---

### День 9: Ручной триггер + fallback + тесты

> **Цель:** кнопка в интерфейсе, scheduler закомментирован.

- [ ] ⏳ Кнопка «🧠 Что я заметил» в меню «Статистика»
- [ ] ⏳ Хендлер `weekly_insight` — ручной вызов
- [ ] ⏳ Scheduler закомментирован в `scheduler.py`
- [ ] ⏳ Feature flag `WEEKLY_INSIGHT_ENABLED` управляет всем
- [ ] ⏳ Тесты: `test_weekly_insights.py`
- [ ] ⏳ `ruff check` + `ruff format` + `pytest`

---

### День 10: Dogfooding AI

> **Цель:** проверить качество сводок на себе.

- [ ] ⏳ Пользоваться 2-3 дня, вызывать weekly insight
- [ ] ⏳ Проверить: интересно ли читать? Не выдумывает ли LLM?
- [ ] ⏳ Проверить fallback при отключенном API
- [ ] ⏳ Записать найденные проблемы

---

## После 2 недель — стоп

- [ ] ⏳ Версия зафиксирована
- [ ] ⏳ 5-10 пользователей на 7-14 дней
- [ ] ⏳ Собрать фидбек: записывают ли? возвращаются ли? понимают ли лимит? читают ли сводку? что раздражает?

---

## Что НЕ делаем в этой сессии

- ❌ Удаление FSM-состояний/хендлеров (нужны EditBudget)
- ❌ Удаление полей модели (обратная совместимость)
- ❌ `mandatory_spent` / `mandatory_paid`
- ❌ `BUDGET_COMPLETE_SLIM` как отдельная ветка (всегда slim)
- ❌ Авто-рассылка AI (scheduler закомментирован)
- ❌ AI-чеки / голос / геймификация / маскот
- ❌ Переписывание архитектуры