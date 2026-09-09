# SESSION_PLAN.md — План сессии на 2 недели

> Статус в начале файла. Обновляй в конце каждой сессии: что сделано, что дальше.

---

## 📊 Статус

| Статус | Кол-во задач |
|--------|:------------:|
| ✅ Готово | 43 |
| 🔧 В работе | 0 |
| ⏳ Ожидает | 2 |

**Следующая задача:** Редактура Утра 1-26 без Кубышки (твоя таблица `Бро, ты машина / Красиво / Брооооо`) → Вечер → Статус

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

### День 5.5: ADR + Hard clean Кубышки + Recovery≠Recalc — ✅ Готово (2026-09-07)

> **ADR:** `Recalculate (free_money, источник истины) ≠ Recovery (временный target/total_days, frozen B) ≠ Savings/Cubby deleted`. Поток `Fact → Recalc? → Recovery? → Normal`. `RECOVERY_ENABLED` — kill-switch, не бизнес-if. `tail=7` — объяснить один раз человечно.
> **ADR-2 (2026-09-07):** `Zone=состояние, Recovery=действие`. Зоны и код `pct>80 🟢/>=51 🔵/>=26 🟡/<26 🔴` `menu.py:546` остаются без изменений. При `Recovery offer/active` `menu.py:611`/`morning_report.py:369` zone footer не показывается, вместо него Recovery footer `phrases.py:693,698`. Zone label всегда по `pct`, не зависит от Recovery. После `finished` — обычный footer. Только 1 фраза меняется: `RECOVERY_DAILY_OFFER` → `💡 Есть варианты восстановить лимит. Сейчас: {dl_pred} ₽/день. Разрулим, бро.`

- [x] ✅ `phrases.py` — удалил 15 фраз Кубышки: `MORNING_*_SIM_*` 10 + `STATUS_FOOTER_*_CUBBY_*` 5→`RED_NONE_*` 3 + `BTN_USE_SAVINGS_*` 5 + `ERR_SAVINGS_EMPTY` + `BTN_SAVINGS`/`ROLLOVER_CARRIED_SAVINGS`/`STATUS_RESERVE_SAVINGS` + добавил `RECOVERY_TAIL_LINE_OFFER`
- [x] ✅ `morning_report.py:26,183` — убрал `savings/dl_simulated/pct_sim/FROM_*`, схлопнул `YELLOW_SIM_GREEN/BLUE`→`YELLOW_SIM_NONE`, `RED_SIM_*`→`RED_DEAD`, ветки `MORNING_*_SIM_*` 10 удалены
- [x] ✅ `menu.py:525,696,745,817` — `_build_status` без `dl_simulated/pct_sim`/`STATUS_RESERVE_SAVINGS`, футеры `YELLOW_CUBBY/RED_CUBBY`→`YELLOW_NONE/RED_NONE`, `_build_status_keyboard` упрощён до `REGULAR`, `handle_use_savings` удалён, `handle_fix_overdraft:cubyshka`→`ERR_GENERIC`
- [x] ✅ `menu.py:400,776,1335` + `keyboards.py:85` — `rollover_keep/_finish_new_period` без `black_day`, `ADVANCED_PLANNING_TITLE` без Кубышки, `get_advanced_planning_keyboard` 2 кнопки (без Кубышки), `adv_black_day` заглушка
- [x] ✅ `menu.py:788,907` — `recovery_show/choose` `RECOVERY_TAIL_LINE_OFFER` `, чтобы оставить запас до конца периода` один раз при выборе, `RECOVERY_PERIOD_END` уже человечно
- [x] ✅ `tests/test_settings_keyboard.py:28` — `Кубышка not in labels`, `ruff --fix --select F,I`, `pytest 357 passed` (было 1 failed), 1 юзер → full clean без миграции

### День 5.6: Утро 17 фраз — полировка (2026-09-07) — ✅ Готово

> **Цель:** `YESTERDAY с ты`, `дн.→days_text`, убрать `🟩🟨🔴`, оставить `📉`/`🏁`/`🥳`, добавить `Бюджет нервничает`.

- [x] ✅ `phrases.py:322-337` — `YESTERDAY_OK/OVER` `ты потратил`, `ZONE_END_EMPTY_1` `Осталось {days_text} — дотянем`, `ZONE_END_OK_1` `!`, `ZONE_END_OK_2` `Бро, мы красиво заходим`, `MORNING_RED_DEAD_1` `Пересчитаем и едем дальше`, `MORNING_YELLOW_BUDGET_NERVOUS` `Бюджет уже нервничает`
- [x] ✅ `phrases.py:329-337` — убраны `🟩🟨🔴` из `ZONE_GREEN_*/YELLOW_*_NONE/RED_DEAD`, оставлены `📉` `ZONE_YELLOW_LIGHT_*`, `🏁`/`🥳` финиш
- [x] ✅ `morning_report.py:20,185` — `_plural_days` + `days_text=f"{days} {word}"` `день/дня/дней`, `ZONE_END_*` `days_text`, `YELLOW_SIM_NONE` 3 варианта `random.choice(3)` с `BUDGET_NERVOUS`
- [x] ✅ `phrases.py:698` — `RECOVERY_DAILY_OFFER` `Есть варианты восстановить лимит. Разрулим, бро.` — 1 фраза по правилу `Zone footer заменяется`
- [x] ✅ `ruff --select F,I passed`, `pytest 357 passed`, финиш `4/4` с `бро` — норм (3 дня, `≈10%` утр)

### День 5: Dogfooding (после Hard clean)

> **Цель:** пройти полный цикл пользователем. Код не писать.

- [ ] ⏳ Новый пользователь → `/start` → доход → период → финал
- [ ] ⏳ Добавить трату → статус → ещё трату → статус
- [ ] ⏳ Настройки → Доп. планирование → задать обязательные (Кубышки нет)
- [ ] ⏳ Статус с обязательными (проверить `recalc` без Кубышки)
- [ ] ⏳ Новый период → ролловер → проверить перенос обязательных (без Кубышки)
- [ ] ⏳ Записать найденные баги/неудобства

### День 5.7: Баги от 2026-09-07 — ✅ Починено (2026-09-07)

> **Цель:** зафиксировать и починить 2 бага из dogfooding.

- [x] ✅ **B1 recalc→Recovery не предложился (RECOVERY_ENABLED=true):** `101617 → 7816 ₽/день (B=10000, 13 дн.)` `menu.py:1966` `free_money=101617` → `invalidate_recovery_offer_context` `recovery_service.py:203` `dismissed=false/last=None` при любом `recalc` (новая реальность), пассивно — следующий `_build_status` `menu.py:611` покажет `RECOVERY_DAILY_OFFER` `phrases.py:698` `Разрулим, бро` если `calculate_recovery_options` валиден. `cooldown 3д/0.5*B` `recovery_service.py:146` остаётся для `Не сейчас` без `recalc`.
- [x] ✅ **B2 вечер 22:00 `Посмотреть отчёт` молчит, 23:30 работает:** `evening_flow.py:125` `@callback show_final_evening_report + EveningState.filling` требовал `state==filling` — при потере FSM (рестарт) игнор → спиннер. Починено: `evening_flow.py:125` фильтр снят, внутри `get_state()` + `is_filling` лог fallback, `try/except/finally always callback.answer()` + `ERR_REPORT_FAILED` `phrases.py:62`, защита от stale — `msg_date != today` `get_msk_now()` → молча `edit_reply_markup(None)` + `state.clear()` без нового отчёта (лучше ничего не слать, чем не тот день).
- [x] ✅ **B3 Остановить восстановление остаётся (RECOVERY_ENABLED):** `middleware.py:19` `_last_keyboard: dict[int,int]` 1 слот — утро 08:00 `msg_A` с `BTN_RECOVERY_STOP` затиралось статусом `msg_B`, `KeyboardCleanupMiddleware` `middleware.py:22` `pop` чистил только `B`, `A` оставалось. Починено: `middleware.py:19` `dict[int,set[int]]` до 5 + `Lock per chat` `_get_lock`, `AutoTrack` `middleware.py:55` `add` под `Lock` с лимитом 5, `rich_api.py:34` `discard` вместо `pop`, гонка 2 сообщений с клавиатурами под `Lock` не теряет `set`.

### День 5.8: Хотелка выпилена (2026-09-07) — ✅ Готово

> **Цель:** выпилить Хотелку как сущность (1 юзер, 0 пользы за 2 мес, не в онбординге). Баг: `0` оставлял `Wishlist.current_amount 8023` `goal_service.py:20` → `Статус` `Хотелка 8,023` и `Хотелка не уходит` при `0`.

- [x] ✅ `phrases.py` — удалён `BTN_WISHLIST`, `WISHLIST_EDIT_PROMPT`, `WISHLIST_SAVED`, `ROLLOVER_CARRIED_WISHLIST`, `STATUS_RESERVE_WISHLIST`; `ADVANCED_PLANNING_TITLE` без `🎯 {wishlist}`, `SAVINGS_UPDATED` оставлен для `save_black_day` совместимости
- [x] ✅ `keyboards.py:85` `get_advanced_planning_keyboard` 1 кнопка `Обязательные` + `Назад` (без Хотелки)
- [x] ✅ `menu.py:557,2015,2228` — `_build_status` без `wishlist_amount`/`STATUS_RESERVE_WISHLIST`, `_render_advanced_planning` без `wishlist`, `adv_wishlist/edit_wishlist` заглушки, `save_wishlist` `invalidate` `Wishlist` `is_active=false/current=0` + `Budget.wishlist_*`, `tests/test_settings_keyboard.py:32` `Хотелка not in labels`
- [x] ✅ `ruff --select F,I passed`, `pytest 357 passed`, `Хотелка 0` → скрыта из `Резервов`

### День 5.9: Остаток/Лимит snapshot + Recovery 100% + Дневной лимит Recovery — ✅ Готово (2026-09-07) — 1 коммит

> **Цель:** починить `Остаток 101617/Лимит 9237` не меняется после `recalc` + `Recovery` `90%→100%` + `Дневной лимит` в `Recovery` с `Лимит на сегодня` `menu.py:530`.

- [x] ✅ `models.py:57` `Budget.spent_at_recalc Float 0` + `database.py:13,184` `ALLOWED_COLUMNS` + миграция `spent_at_recalc REAL/FLOAT` — `free_money` snapshot + `c было`
- [x] ✅ `budget_service.py:189` `apply_reconciliation` атомарно `free_money + spent_at_recalc = spent_period` `budget_service.py:167` `reconcile`, `save_budget` `spent_at_recalc=0`, `_current_money_for_life` `free - max(spent - spent_at,0)` — единая `max(...,0)`
- [x] ✅ `menu.py:525,morning_report.py:145,evening_flow.py:142,evening_report.py:239,menu.py:763,854,949` — везде `if free>0: spent_at → money` иначе `income-mandatory-spent`, `evening_flow` `available_cash` уже `money`, `evening_report` `deficit` через новую `money`
- [x] ✅ `recovery_service.py:114` `check_success 0.90→1.00` `Decimal("1.00")`, `morning_report.py:253` уже без кода
- [x] ✅ `menu.py:580` `_build_status` `if active: dt=target 6000, free=max(target-spent_today,0) 950` порядок `БАЛАНС·🟢` / `Сегодня` / `🧘 день 1/5` + `Лимит на сегодня: 6000` / `Свободно 950·Потрачено 5050` / `После восстановления — 10000` / `Период Остаток·Прогноз 8468` `dl_pred`, `footer` скрывать когда `recovery_offer/active` → `Идём по плану 👍` reuse `RECOVERY_DAILY_ACTIVE` `phrases.py:690`
- [x] ✅ `ruff --select F,I passed`, `pytest 357 passed`, `Остаток` теперь `101617-3700=97917` падает, `Лимит` `97917/12` движется, `evening_flow` без двойного минуса

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