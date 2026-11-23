# SESSION_PLAN.md — План сессии на 2 недели

> Статус в начале файла. Обновляй в конце каждой сессии: что сделано, что дальше.

---

## 📊 Статус

| Статус | Кол-во задач |
|--------|:------------:|
| ✅ Готово | 219 |
| 🔧 В работе | 0 |
| ⏳ Ожидает | 38 |

**Следующая задача:** «Конверты», M5 → M6. G2, G2.1 и карточка C1–C3 готовы; остались ассеты лягушек и ручная проверка карточки в Telegram.

> Контекст, цитаты пользователя и цифры для тестов — `agent/bugs_2026-11-06.md`.

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

### День 4.5: Recovery v1-infra (✅ включён 2026-09-05)

> **Цель:** временный режим поверх `Budget.daily_limit` — `B` frozen, 60/70/80%, `+7`, `85/90/110`, `get_user_now` tz-aware. Review: `datetime.now()` → `get_msk_now()`.

- [x] ✅ `models.py:58` — `Budget.base_daily_limit` nullable Float (frozen B)
- [x] ✅ `models.py:159,181` — `RecoveryState` (`recovery_states`) + `RecoveryOfferState` (`recovery_offer_state`) + `_get_user_now` wrappers
- [x] ✅ `database.py:13,204` — `ALLOWED_TABLES/COLUMNS` + миграция `base_daily_limit` + `CREATE TABLE IF NOT EXISTS` (SQLite/PostgreSQL)
- [x] ✅ `config.py:18` — `RECOVERY_ENABLED` (включён в `19755f0`, 2026-09-05) + 10 констант `TRIGGER 0.85, FAST 0.60...`
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

### День 5.9: Остаток/Лимит snapshot-канон (основательный, без костыля) — ✅ Готово (2026-09-09) — 1 коммит

> **Цель:** починить `Остаток 101617/Лимит 9237` застыл после `c5cb187` отката + ввести единый канон snapshot без `getattr`/`black_day`/дублей. `get_money_for_life`/`get_period_spent`/`get_daily_pred` + `get_period_dates` единственный источник границ `[period_start, next_day)`.

- [x] ✅ `budget_service.py:192` `get_money_for_life(budget, spent_period)=free-max(spent-spent_at,0) if free>0 else income-mandatory-spent` (прямой `budget.spent_at_recalc`, без `getattr`, `black_day` исключён, сохраняет `_current_money_for_life` alias), `get_daily_pred(money,days)` чистая, `get_period_spent(telegram_id,budget)` через `monthly_report.get_period_dates` полуинтервал — единый источник `spent_period`
- [x] ✅ `menu.py:97` `_handle_recovery_budget_change` + `486` `_build_status` + `765` `recovery_show_options` + `844` `recovery:chouse` + `930` `recovery:dismiss` — везде через канон, убран дубль `if free>0`/`getattr`/`black_day`, `_build_status` `584/652` дубль `get_active_recovery`/`resolve_frozen_baseline` схлопнут в один fetch с reuse `_recovery_active/_recovery_offer`
- [x] ✅ `evening_flow.py:157` `finalize_evening_report` — схлопнут дубль `if free>0` (две ветки `total_available`+`available_cash` → `money_for_life`+`get_daily_pred`), удалён `black_day`, `get_current_period_expenses_sum`→`get_period_spent`
- [x] ✅ `morning_report.py:149` + `evening_report.py:228` — через канон, `else` без `black_day`, `evening_report.py:229` `__import__("datetime")`→`timedelta` import, `morning_report` убран `get_current_period_expenses_sum`
- [x] ✅ `models.py:58`+`database.py:216` `spent_at_recalc REAL/FLOAT` уже были, инварианты закреплены: `reconcile`→preview, `apply_reconciliation`→commit `free+spent_at`; `recovery 1.00` без изменений
- [x] ✅ `budget_service.py:96` `save_budget UPDATE` больше не зануляет `spent_at_recalc` (только `INSERT 109` `default 0`) — `39efc3d` 1 удаление, сохраняет `free+spent_at=192546` после `Recalc B`, `rollover/mandatory` не ломают снапшот, `free==0 → income-mandatory-spent`
- [x] ✅ `ruff --select F passed` (`E501` 28 оставлено), `pytest 357 passed`, сценарии: `101617-(1540-1240)=101317` после `+300`, `101617-(4940-1240)=97917` контекст, факт `X → X` после `Recalc B` (`X - (192546-192546)=X`)

### День 5.10: Вечер — редактура фраз (итоговая таблица) — ✅ Готово (2026-09-11) — 1 коммит
> **Цель:** `Evening` канон по твоей таблице: `INITIAL/CONTAINER/LINE/SAVED/TIMEOUT` + `ZERO 3` + `GREEN 1 strong (<0.5×) + 3 ordinary (0.5×≤spent≤limit)` + `OVER 2 ordinary (limit<spent≤2×) + 1 strong (2×<spent≤3×) + 1 extreme (>3×) + AUTO_CLOSE 4` (5→4), без Кубышки/Хотелки, `get_evening_message` 6 веток `spent==0 / <0.5*limit / ≤limit / ≤2*limit / ≤3*limit / >3*limit` (сильные 1/1, обычные random).

- [x] ✅ `phrases.py:293-314` `INITIAL/CONTAINER/TIMEOUT` упрощены `👁 День подошёл…` / `Вот что набралось…` / `⏱ Время вышло…`, `ZERO_1-3` без `frugal/финансовый отчёт`, `GREEN_1` strong `machine + {saved}`, `GREEN_2-4` ordinary, `OVER_1-3` без `гречка/аудит/супер-эконом`, `SPECIAL 🛌` `>3×`, `AUTO_CLOSE 5→4` `Полночь близко/День закрыт`
- [x] ✅ `evening_report.py:49` `get_evening_message` разветвлён `spent==0 → ZERO random 3, <0.5*limit → GREEN_1 1/1, ≤limit → GREEN_2-4 random 3, >3*limit → SPECIAL, >2*limit → OVER_3, else OVER_1-2 random 2`, `saved=limit-spent`, `over=spent-limit`, `ruff --select F passed` `pytest 357 passed`

---

### B6: `is_active` NOT NULL без DEFAULT — ✅ Готово (2026-11-04) — 1 коммит

> **Цель:** новый пользователь не регистрировался на проде: `null value in column "is_active" violates not-null constraint` (3 попытки `405687370`, 02–03.11).

- [x] ✅ Прод hotfix: `ALTER TABLE users ALTER COLUMN is_active SET DEFAULT TRUE` (metadata-only)
- [x] ✅ `database.py:106` `_ensure_user_is_active_default(conn)` — идемпотентная PG-миграция: dialect-guard, `table_schema = current_schema()`, skip при дефолте `true`
- [x] ✅ `database.py:170` вызов в `migrate_schema()` после миграции PK
- [x] ✅ `ALLOWED_COLUMNS += "is_active"` — иначе `_has_column` → `Unauthorized SQL identifier`
- [x] ✅ `tests/test_database.py` — 13 тестов (legacy / `false` / `true` / нет колонки / нет метаданных / SQLite / wiring / whitelist / ALTER-fail / WARNING / search_path)
- [x] ✅ `ruff check .` + `ruff format --check .` + `pytest 366 passed`
- [ ] ⏳ `DROP COLUMN is_active` — отдельным коммитом после стабилизации

---

### B7: Гейт `ADMIN_IDS` на `/test_*` — ↩️ Отменено в B10

> ⚠️ Все четыре `/test_*` команды и `ADMIN_IDS` удалены 2026-11-05. Пункт оставлен как история.

> **Цель:** `/test_morning` и `/test_teaser` рассылают всем пользователям, но были доступны любому.

- [x] ✅ `config.py` — `ADMIN_IDS: str = ""` + `settings.admin_ids` (запятые, `try/except int`, только > 0)
- [x] ✅ `test_commands.py` — `AdminOnlyMiddleware` на роутере + `_is_admin()` в 4 хендлерах
- [x] ✅ Fail closed: пустой `ADMIN_IDS` → команды недоступны никому
- [x] ✅ `/test_evening` без `message.delete()` (RULES 12.3)
- [x] ✅ `.env.example` + README Variables (таблица)
- [x] ✅ `tests/test_test_commands.py` — 20 тестов (парсинг/мусор/Settings/4 команды/3 middleware/регистрация/админ-путь)
- [x] ✅ `ruff check .` + `ruff format --check .` + `pytest 385 passed`
- [x] ✅ Исторически: `ADMIN_IDS=412762673` был прописан в сервисе бота в Railway (переменная больше не читается)

---

### B8: Schema audit — ✅ Готово (2026-11-04)

> **Цель:** ловить дрейф «ORM vs реальная БД» до деплоя, а не по жалобе нового юзера.

- [x] ✅ `src/db/schema_audit.py` — `model_schema()` / `compare_schemas()` / `read_actual_schema()` (PG `information_schema` + `current_schemas`, SQLite `PRAGMA table_xinfo`)
- [x] ✅ critical: нет таблицы/колонки, legacy `NOT NULL` без default, `nullable`-модель при `NOT NULL` без default; warning: legacy-колонка, оба направления nullable-дрейфа; info: лишняя таблица
- [x] ✅ exit 1 при critical, 0 при чистоте, 2 при ошибке чтения; только чтение
- [x] ✅ Живая проверка: legacy-SQLite → critical + exit 1; чистая база → exit 0
- [x] ✅ `tests/test_schema_audit.py` — 17 тестов: `compare_schemas`, `model_schema`, чтение PG/SQLite, exit codes, ошибка чтения
- [x] ✅ `ruff check .` + `ruff format --check .` + `pytest 407 passed`

---

### B9: `/test_*` бьют только по админу — ↩️ Отменено в B10

> ⚠️ Команды удалены целиком 2026-11-05; `user_ids`/`force`/возврат получателей убраны из сервисов. Пункт оставлен как история.

> **Цель:** тестовые команды не должны трогать реальных пользователей.

- [x] ✅ `send_morning_reports(bot, user_ids=None, *, force=False) -> list[int]` — без аргументов все, с `user_ids` только они; `force=True` пропускает дневной дедуп и не пишет `daily_reports_log`
- [x] ✅ `send_evening_teaser(bot, storage, user_ids=None) -> list[int]` — тот же фильтр получателей
- [x] ✅ `/test_morning` и `/test_teaser` передают `[message.from_user.id]`; `/test_evening` и `/test_monthly_summary` уже были админскими
- [x] ✅ Обе команды отвечают по факту: «отправлено тебе» / «не отправлено» (нет бюджета, уведомления off, занят в вечерней сессии); тексты в `phrases.py`
- [x] ✅ Планировщик и утренний запуск в `main.py` без аргументов → шлют всем, как раньше
- [x] ✅ `tests/test_report_recipients.py` — 9 тестов: фильтр получателей, `force` без дедупа и без лога, возврат получателей, отсутствие лога при ошибке отправки
- [x] ✅ `tests/test_test_commands.py` — 23 теста (аргументы админа + отчёт о результате)
- [x] ✅ `ruff check .` + `ruff format --check .` + `pytest 419 passed`

---

### B10: Удаление всех `/test_*` — ✅ Готово (2026-11-05)

> **Причина:** `/test_morning` писал `daily_reports_log` и «съедал» плановый отчёт (инцидент 2026-11-04, отчёт ушёл в 02:40 вместо 08:00). Команды нужны редко и дают побочные эффекты.

- [x] ✅ Удалён `src/bot/handlers/test_commands.py` + подключение в `main.py`
- [x] ✅ `send_morning_reports(bot)` / `send_evening_teaser(bot, storage)` без `user_ids`/`force`/возврата; безопасная запись лога и пауза 50 мс сохранены
- [x] ✅ Удалены `ADMIN_IDS` / `settings.admin_ids` и `TEST_*` из `phrases.py`
- [x] ✅ Удалены `tests/test_test_commands.py`, `tests/test_report_recipients.py`; добавлен `tests/test_morning_report.py` (лог ровно один раз, дедуп не пишет)
- [x] ✅ README, `.env.example`, `PHRASE_MAP.md`, `PHRASE_TABLE.csv` обновлены
- [x] ✅ `ruff check .` + `ruff format --check .` + `pytest 389 passed`

---

## Bug Audit 2026-11-06 — P0/P1/P2

> Полный разбор с цитатами пользователя, цифрами и файлами — `agent/bugs_2026-11-06.md`.
> Порядок важен: сначала деньги (B11, B12), потом визуал и зоны, редактура — последней.

### Порядок задач

1. **B11** — месяц бюджета / добавление дохода
2. **B12** — план на сегодня / «Свободно» / дни периода
3. **B16** — визуальный пакет
4. **B15** — `ADMIN_CHAT_ID` + фраза ошибки
5. **B13** — зоны и тон
6. **B14** — Recovery (после решения A/B)
7. **B17** — редактура фраз
8. **B18** — месячный отчёт

---

### B11: месяц бюджета и добавление дохода — ✅ Готово

> **Цитата:** «Я ввела доп 10000… Ожидаю увидеть что сейчас 9000 свободно. А он пишет… Остаток 0 ₽ · Лимит 0 ₽/день… Тоже жопа показывает нет лимита».
> **Контекст:** 17 сентября, период 20.08–19.09. Активный бюджет — август, `update_budget_field` пишет в сентябрь → молчаливый no-op.

- [x] ✅ `budget_service.py` — правки по `budget.id` активного бюджета, не по `month == now`
- [x] ✅ `menu.py` — онбординг с будущим стартом сохраняет в месяц, который найдёт `get_active_budget`
- [x] ✅ `menu.py` — `free_money > 0` → «Свободно», иначе → «Доход»; `base_daily_limit` пересчитывается
- [x] ✅ `evening_flow.py` — при бюджете и `limit == 0` показывать отчёт, а не «нет бюджета»
- [x] ✅ Тесты: `month_for_period_start`, активный бюджет прошлого месяца, пересчёт базы, re-anchor дня старта, удаление активного, вечер с нулевым лимитом, сообщение о доходе
- [x] ✅ `pytest 520 passed`, `ruff check .`, `ruff format --check .`

**Ожидаемо:** `24 933 - 18 343 = 6 590` свободно (при `mandatory=0`), а не `0`. «9 000» из цитаты — неточная арифметика пользователя; главное — статус должен измениться.

---

### B12: план на сегодня / «Свободно» / дни — ✅ Готово

> **Цитата 1:** «Не поняла потрачено 9010 а лимит 9300 почему свободно 0» — при плане 9 361 и тратах 9 015.
> **Цитата 2:** «Тут прям сильный баг с лимитом где остаток дней. У должно делиться вся сумма на дни без сегодняшнего» — 159 149 / 18 дн.

- [x] ✅ `menu.py` — `plan_today = (money_for_life + spent_today) / days_left`, `free_today = max(plan_today - spent_today, 0)`
- [x] ✅ Убрано двойное вычитание `dl_pred - spent_today`
- [x] ✅ «Остаток» — отдельная строка; «Свободно» и «План на сегодня» не смешиваются
- [x] ✅ Подпись периода по `period_end.day` («до 19-го», не «до 20-го»)
- [x] ✅ `models.py` + `budget_service.py` — фактическая длина периода (28–31), не 30
- [x] ✅ `morning_report.py` / `evening_flow.py` — те же числа, что в статусе
- [x] ✅ Тесты: `159 149 / 3 669 / 18` → план 9 045, свободно 5 376; `150 134 / 9 015 / 17` → план 9 361, свободно 346; 31/30/28/29 дней
- [x] ✅ Регресс: `days_remaining` включает сегодня (все существующие тесты проходят)

**Формула:**
```text
plan_today = (money_for_life + spent_today) / days_left
free_today = max(plan_today - spent_today, 0)
overrun_today = max(spent_today - plan_today, 0)
tomorrow_plan = money_for_life / max(days_left - 1, 1)
remaining_period = money_for_life
```

**Уточнение 2026-11-10 — фиксированный «Лимит»:**
- [x] ✅ «План на сегодня» = `plan_today` напрямую, **не** `free_today + spent_today`
- [x] ✅ План не меняется от трат в течение дня
- [x] ✅ При `overrun_today > 0` показывается отдельно: `Свободно 0 ₽ ⛔ · Потрачено 18 343 ₽ · Перерасход 8 982 ₽`; план остаётся утренним `9 361 ₽`
- [x] ✅ Добавка дохода среди дня пересчитывает `plan_today`
- [x] ✅ Тесты: план `9 045` не меняется после траты ещё 1 000 ₽; при перерасходе план `9 361` не растёт, перерасход `8 982` отдельно

---

### B16: визуальный пакет — ✅ Готово

- [x] ✅ `expense_service.py` — `🐱 Киси Кошке: Суролан — 1,644₽`; дедуп «описание = категория» сохранён
- [x] ✅ `evening_report.py` — `<blockquote>` вместо литеральных `>`; вынесено в `_build_teaser`
- [x] ✅ Убрано «👋 Выбери действие:» (`WELCOME_MENU` удалён, три отправки в `menu.py` убраны)
- [x] ✅ `phrases.py` — убрана «гречка» из `STATUS_FOOTER_YELLOW_NONE_3`
- [x] ✅ `monthly_summary.py` + `keyboards.py` — в кнопках только период; «🔄 Обновить» отдельной строкой
- [x] ✅ Тесты: `test_b16_visuals.py` (9)

---

### B15: ADMIN_CHAT_ID и фраза ошибки — ✅ Готово

- [x] ✅ `config.py` — `ADMIN_CHAT_ID: int | None = None` (не возвращать `ADMIN_IDS`)
- [x] ✅ `error_notify.py` + `main.py` — traceback + `user_id` + тип update админу; ошибка отправки не роняет бота
- [x] ✅ `phrases.py` — «😨 Ой-ёёёй, случилась ошибочка! / Мы уже оповестили администратора» (цитатой)
- [x] ✅ `.env.example`, README Variables, тесты с админом / без / send fail (`test_error_notify.py`, 22)

---

### B13: зоны и тон — ✅ Готово

- [x] ✅ Единая зона периода: 70 / 90 / 100 (`status_zones.period_zone`, как в RULES и месячном отчёте)
- [x] ✅ День: `free_today > 0` / `== 0` / перерасход (`apply_day_state`)
- [x] ✅ Утро: не пишем «притормаживаем», если вчера «уложился» (`YELLOW_LIGHT_OK`); не пишем «нервничает», если лимит вырос
- [x] ✅ Запрещён 🟢 при `free_today == 0` (зона понижается до жёлтой) и при перерасходе — красная
- [x] ✅ Фактор 1: `pct = plan_today / base_daily_limit * 100`, база — `(доход − обязательные − кубышка) / дни периода` (`get_base_daily_limit`), **не** `budget.daily_limit`
- [x] ✅ Фактор 2: `overrun_today > 0` запрещает зелёные/расслабленные фразы, даже если `pct` зелёный
- [x] ✅ `tomorrow_plan < plan_today` → цифра в прогнозе; `>=` → без цифр и без «подрастёт» (`forecast_amount`)
- [x] ✅ Последние 3 дня — финальные фразы, прогноз на завтра не показывается
- [x] ✅ Тесты: `test_b13_zones.py` (47)

---

### B14: Recovery — ✅ Готово

- [x] ✅ Решение **B**: досрочное закрытие разрешено, но с явной фразой «Ты восстановился раньше срока»
- [x] ✅ `recovery_service.py` — `recovery_day_number()` + `is_early_completion()`
- [x] ✅ `menu.py` — бюджет-хук: `early_success` + `RECOVERY_SUCCESS_EARLY`, иначе `RECOVERY_BUDGET_DONE`
- [x] ✅ `morning_report.py` — досрочный успех показывает `RECOVERY_SUCCESS_EARLY`, плановый — `RECOVERY_SUCCESS`
- [x] ✅ `tests/test_b14_recovery.py` — день 1 из 5, плановое закрытие, нехватка дохода (сокращение без закрытия)
- [x] ✅ `pytest 531 passed`, `ruff check .`, `ruff format --check .`

---

### B17: редактура фраз — ✅ Готово

- [x] ✅ `EVENING_ZERO_1/2/3` — спокойно, без подозрений
- [x] ✅ «Лимит сожмётся до {X}» — только при реальном снижении, `X` = `tomorrow_plan`
- [x] ✅ Убрано обещание роста в `EVENING_GREEN_1`; `EVENING_GREEN_3` оставлен только при реальном росте
- [x] ✅ «Сегодня полегче» — убрано из футера, в утренней фразе оставлено по решению пользователя
- [x] ✅ Утро 1–26 — честный прогноз без «денег нет»
- [x] ✅ `pytest 531 passed`, `ruff check .`, `ruff format --check .`

---

### B18: месячный отчёт — ✅ Готово

- [x] ✅ «Сэкономлено: X ₽» / «Перерасход: X ₽» (`income - total_spent`), только для закрытого периода
- [x] ⏸ «Остаток перенести в новый период?» — отложено решением пользователя (пока не делать)
- [x] ✅ Убраны из `MONTHLY_DETAILS` Кубышка, Хотелка, округление; отдельная строка округлений тоже убрана
- [x] ✅ `tests/test_b18_monthly.py` — сэкономлено/перерасход/ноль/активный период + чистка деталей
- [x] ✅ `pytest 537 passed`, `ruff check .`, `ruff format --check .`

---

## Сессия 2026-11-15/16 — B19–B22 (визуал и утренний отчёт)

> B19–B22 не входили в исходный Bug Audit; добавлены по решению пользователя 2026-11-15/16.
> Правило: 1 задача = 1 коммит. Перед коммитом — утвердить фразы/вариант.

### B19: эмодзи зон в статусе и месячном отчёте — ✅ Готово

**Проблема:** шапка статуса и месячный отчёт используют пёстрые 🟢🔵🟡🔴; «Свободно 0 ₽» — ⛔.

- [x] ✅ Вариант: **только текст**, без цветных кружков и ⛔
- [x] ✅ `menu.py` — шапка `БАЛАНС · В норме`, `zone_labels` вместо `zone_emoji`
- [x] ✅ `phrases.py` — `STATUS_REMAINING_ZERO = "Свободно 0 ₽"`, `STATUS_REMAINING_OK` без 🟢, `MONTHLY_ZONE_TAG = "Зона: {zone_label}"`
- [x] ✅ `monthly_report.py` — `_zone_for_period` возвращает только подпись
- [x] ✅ `tests/test_b19_visuals.py` — нет зонных эмодзи в статусе и отчёте
- [x] ✅ `pytest 540 passed`, `ruff check .`, `ruff format --check .`

**Варианты:**
1. Только текст: `БАЛАНС · В норме`, `Свободно 0 ₽`, `Зона: Зелёная`.
2. Спокойные символы: `● / ◐ / ○ / ✕`, ⛔ убрать.
3. Другие эмодзи: `✅ / 🔷 / ⚠️ / ❌`, ⛔ убрать.

### B20: обрезанная кнопка «➕ Дополнительный доход» — ✅ Готово

**Проблема:** кнопка стояла в одном ряду с «💳 Остаток на карте» и обрезалась.

- [x] ✅ Вариант: **каждая кнопка в свой ряд**
- [x] ✅ `keyboards.py` — `get_change_budget_choice_keyboard`: «➕ Дополнительный доход», «💳 Остаток на карте», «⬅️ Назад» отдельными рядами
- [x] ✅ `tests/test_b20_keyboard.py` — три ряда по одной кнопке
- [x] ✅ `pytest 541 passed`, `ruff check .`, `ruff format --check .`

**Варианты:**
1. Каждая кнопка в свой ряд (широкие).
2. Сократить подпись до «➕ Доход», оставить в одном ряду.
3. И разнести, и сократить.

### B21: ложное «доброе утро» при старте в 5 утра — ✅ Готово

**Причина:** `src/bot/main.py:74` — условие `5 <= msk_now.hour < 12`. При передеплое Railway старт в 5 утра запускал утренний отчёт, хотя плановая рассылка стоит на 08:00. Защита `_has_morning_report_today` исключает только повторную отправку, но не первый запуск при старте.

**Что сделано:**
- `src/utils/helpers.py` — константы `MORNING_CATCHUP_START=8`, `MORNING_CATCHUP_END=12` и функция `is_morning_catchup_window(now)`.
- `src/bot/main.py` — условие заменено на `is_morning_catchup_window(msk_now)`. Окно — 08:00–12:00: раньше 08:00 догонять нечего.
- `src/services/morning_report.py:108` — лог пишет просто «Запуск утренней рассылки...», а не всегда «в 08:00».
- `tests/` — отдельный тест на границы окна не добавлен (меняется одно условие).

**Результат:** передеплой в 5 утра больше не отправляет ложное «доброе утро». Плановая рассылка в 08:00 работает; `misfire_grace_time=14400` (4 ч) покрывает случай «старт в 07:59 — через минуту сработает cron».

- [x] ✅ `pytest 541 passed`, `ruff check .`, `ruff format --check .`

### B22: «Вчера» считается от вчерашнего плана — ✅ Готово

**Проблема:** в одном утреннем сообщении были два разных лимита. `📋 Лимит: 1168 ₽/день` — живой план на сегодня (`dl_pred`), а `📅 Вчера: … из 6666 ₽` — базовый лимит периода (`dl_base` = доход ÷ дни). Пользователь видел вчера совсем другое число и воспринимал это как ошибку.

**Причина:** в `9e687a5` (B11–B13) сравнение «Вчера» перевели с `dl_pred` на `dl_base`, чтобы убрать противоречие «уложился + притормаживаем». Побочка — число перестало совпадать с тем, что показывалось вчера.

**Решение:** восстанавливать вчерашний план из текущих данных, без хранения истории:

```python
plan_yesterday = (money_for_life_raw + yesterday_spent + spent_today) / (days_left + 1)
```

`money_for_life_raw` — остаток **сейчас**, поэтому возвращаем траты обоих дней.

- `src/services/morning_report.py` — новые `_yesterday_plan()` и `_yesterday_line()`; `yesterday_ok`, «перебор» и строки `YESTERDAY_OK/OVER` считаются от `plan_yesterday`.
- Сравнение идёт по тем же целым числам, что показываются, — «перебор 0 ₽» из-за копеек невозможен.
- `dl_base` остаётся только для зон (`_select_morning_zone`) — правило не менялось.
- При перерасходе периода `plan_yesterday = 0` — строка пишет «из 0 ₽» (решение пользователя).
- `tests/test_b22_yesterday_limit.py` — 7 тестов: восстановление, учёт сегодняшних трат, «не базовый лимит», ноль при перерасходе, защита от «перебора 0 ₽».

**Пример:** остаток 3504 ₽, вчера потрачено 7400 ₽, сегодня 0, до конца 3 дня → вчерашний план `(3504 + 7400 + 0) / 4 = 2726 ₽`. Было «из 6666 ₽ — перебор 733 ₽», стало «из 2726 ₽ — перебор 4674 ₽».

- [x] ✅ `pytest 548 passed`, `ruff check .`, `ruff format --check .`

---

## Следующая сессия — месячный отчёт

> Пользователь хочет заниматься этим отдельно. M1–M2 сделаны 2026-11-16, дальше — с M3.

- [x] ✅ **M1** — средний расход в день считается от фактической длины периода. `compute_avg_day()` в `monthly_report.py`: закрытый период — `period_total_days(month, start_day)` (28–31), активный — прошедшие дни включая сегодня `(today − period_start) + 1` с кэпом на длину периода. Строка `MONTHLY_AVG_DAY` не менялась. Тесты: `tests/test_monthly_report.py` (10).
- [x] ✅ **M2** — `det_html.removesuffix("<br>")` вместо `rstrip("<br>")`: старый вызов снимал символы из набора и съедал `>` у `</code>` перед `<br>`, ломая Rich-разметку деталей. Тесты: закрытый `</code>` на конце, точный хвост `Обязательные платежи: …</code>\n</details>`.
- [x] ✅ **M3** — «Без категории» участвует в сортировке: merge именованных + uncategorized, сортировка по `(amount desc, count desc)`, слив дублей по имени. Новые фразы для топа: активный `MONTHLY_EGG_TOTEM_NO_CATEGORY`, закрытый `MONTHLY_TOTEM_NO_CATEGORY` (Чебурашка). Пустой период → `MONTHLY_EMPTY`. Тесты: +3 в `test_monthly_report.py`. `pytest 563 passed`.
- [x] ✅ **M4** — «Сэкономлено/Перерасход» от доступного лимита, без ярлыка «Зона». База `available = total_income − mandatory_payments − black_day_fund`; `compute_saved_state()` округляет остаток до выбора тона (70/90/100), `available ≤ 0` → причина без цифры. Строки `💵 Доход` и `➕ Из них добавлено`. Новый счётчик `Budget.added_income` + миграция; `save_budget` обнуляет, правки обязательных/кубышки — нет. 6 утверждённых фраз, старые `MONTHLY_ZONE_*`/`MONTHLY_BUDGET_LABEL` удалены. Тесты: 594 passed.
- [ ] ⏳ **M5** — убрать дублирующий `get_period_label()`.
- [ ] ⏳ **M6** — тесты на `build_summary_data`: `avg_day`, зона, тотем, порядок категорий. Сюда же — интеграционная связка `build_summary_data` → `compute_avg_day` (review M1, 2026-11-16): нужен патч `src.services.monthly_report.async_session_maker` в `tests/conftest.py`.
- [x] ✅ **G1** — график в месячном отчёте: PNG-карточка (основной путь) + Tier 1 виджет за `MONTHLY_WIDGET_ENABLED` (см. раздел «График в месячном отчёте» ниже).

### Утренние фразы, конверты и остаток `free_money`

- [x] ✅ **B23** — тон последних 3 дней периода. `END_OK` только если вчера уложился И план ≥ 70% базы; `END_YESTERDAY_OVERRUN` (вчера перебор) / `END_PLAN_SAGGED` (план < 70% базы). Float-безопасное сравнение через округлённое значение. Тесты: 9 кейсов в `test_b23_end_of_period.py`. `pytest 603 passed`.
- [x] ✅ **U1** — статус: сумма перерасхода в строке дня (`Свободно 0 ₽ · Перерасход N ₽ · Потрачено M ₽ ⚠️`). `STATUS_OVERRUN` оживлён. Тесты B12/B13 обновлены. `pytest 603 passed`.
- [x] ✅ **U2** — настройки: текущий остаток `money_for_life` вместо снапшота `free_money`; фраза `SETTINGS_MONEY_REMAINING` («💰 Остаток: …»), `SETTINGS_MONEY_FREE` удалена. Тесты: `test_u2_settings.py` (3). `pytest 606 passed`.
- [x] ✅ **U3** — рандом `END_OK/END_OK_1/2` через хелпер `_end_ok_text` + `STATUS_FOOTER_YELLOW_NONE_2`/`RED_NONE_2`; удалены 23 устаревшие фразы, 4 Recovery-фразы оставлены; удалён мёртвый `_build_recovery_morning_extra`; синхронизированы `PHRASE_TABLE.csv`/`PHRASE_MAP.md`. Тесты: `test_u3_phrases.py` (30, включая достижимость всех трёх вариантов). `pytest 641 passed`.
- [x] ✅ **B24** — сообщение после добавки дохода: `✅ Добавлено / 💰 Остаток / Сегодня свободно / Завтра ₽/день`. «Сегодня свободно» считается как в статусе (`get_plan_today` → `get_free_today` с учётом трат сегодня), «Завтра» — `tomorrow_plan` (остаток на дни без сегодня). Шаблон всегда полный, даже при нулях; `INCOME_ADDED_LAST_DAY/EMPTY` удалены. Тесты: `test_b24_income_message.py` (5). `pytest 638 passed`.
- [ ] ⏳ **Конверты** — обязательные платежи как отдельный конверт: списание из конверта не трогает дневной лимит, остаток конверта виден отдельно. Продуктовая задача, M4 её не затрагивал.
- [ ] ⏳ **`free_money` в месячном отчёте** — при `free_money > 0` отчёт считает от `total_income`, а не от фактического остатка (снапшот `free_money + spent_at_recalc`). Согласовать формулу базы для этого режима.

### Находки review B18–B20 (отдельно, не входят в B19/B20)

- [ ] ⏳ **R1** — `ZONE_RED` попадает в `«На нуле»`, хотя `Свободно X ₽`; нужна отдельная фраза для красной зоны (продуктовое решение).
- [ ] ⏳ **R2** — после чистки `MONTHLY_DETAILS` остались лишние запросы `_get_active_wishlist`, `_get_black_day_fund_data`, `_get_rounding_total`; удалить вместе с мёртвыми ключами.
- [ ] ⏳ **R3** — мёртвая фраза `MONTHLY_ROUNDING_LABEL`; удалить. (`STATUS_REMAINING_OK` удалена в U3.)
- [ ] ⏳ **R4** — обновить `docs/PHRASE_MAP.md`, `docs/PHRASE_TABLE.csv`, `README.md`: там ещё старые эмодзи зон и строки про округление/Кубышку. (Частично закрыто в U3: фразы и таблица синхронизированы, остались тексты про Кубышку.)

---

## График в месячном отчёте — G1–G4

> UX-решения зафиксированы 2026-11-16: траты по дням + пунктир базового лимита, нативный HTML-виджет, отдельное сообщение под rich-отчётом, Tier 1 — сразу в G1.

### ✅ G1: график «Траты по дням» + Tier 1 (PNG основной, виджет за флагом) — ✅ Готово

**Продукт:** PNG-карточка «Financial Bro» (900×620) как основной путь: столбики трат по дням, пунктир базового дневного лимита (`get_base_daily_limit`), дни выше лимита — акцентным цветом, инсайты (пик, серия в лимите, топ-3 дня, ночной дожор и т.п.). В активном периоде — только прошедшие дни включая сегодня; закрытый — все 28–31 день. Нативный HTML-виджет + Tier 1 тап-тултип сохранён в коде, но выключен флагом `MONTHLY_WIDGET_ENABLED=False` до возврата виджетов. PNG не отправляет суммы третьим лицам. **Заменено C1–C3 на 900×840.**

**Реализация:**
- `src/services/monthly_chart.py` — `_chart_window()`, `build_chart_data()` (агрегация по дням), `build_chart_state()` (JSON ≤ 1024 байт: `m`, `s`, `d[]`, `lim`, `a`), `build_monthly_card_input()` (реальные расходы, прошлый период, лимит), `render_monthly_card_png()`, `CHART_WIDGET_HTML` (inline SVG/JS ≤ 4096 байт zlib).
- `src/bot/chart_delivery.py` — единая доставка: PNG через `send_or_update_photo` (edit вместо спама), виджет только при флаге; fallback widget → PNG.
- `src/bot/rich_api.py` — `send_widget()` / `edit_widget_data()` с retry+backoff, shared aiohttp session (закрывается на shutdown), обработка 429.
- `src/bot/widget_cache.py` — shared cache ключ `(telegram_id, chat_id)`, per-user `asyncio.Lock`, `send_or_update_photo(..., force_new=...)`.
- `monthly_summary.py` — без ручного `passed_days` и `date - datetime`; навигация обновляет существующее фото, `menu_monthly_report` — свежее внизу.
- `morning_report.py` — авто-ролловер использует тот же `send_monthly_chart`.
- `src/core/config.py` / `.env.example` — `MONTHLY_WIDGET_ENABLED` (default `False`).

**Tier 1 (виджет, за флагом):** тап по столбику показывает тултип — дата, потрачено, лимит, разница; выбранный столбик подсвечен, повторный тап снимает выбор. Tooltip clamping: horizontal `[55, svgW-55]`, vertical (если `top < 42` — под столбиком). Всё локально, без `allow_queries`.

**Критичные фиксы (review G1):**
1. `date - datetime` в хендлерах → нормализация дат на границе сервиса.
2. `float(async get_base_daily_limit(...))` → `await`.
3. `datetime.isoformat()` → `date.fromisoformat()` → `_date_str()` / `_parse_date()`.
4. dict-контракт виджета → нормализованный `message_id`.
5. `expenses` dict vs ORM → единый `CardExpense` (dict) во всём рендере.
6. JS scope `w`/`barH` в `showTooltip` → локальные `svgW`/`barRect.height`.
7. `passed_days = min(30, ...)` → `len(daily_spent)` из сервиса.
8. Кэш писался, но не читался → `send_or_update_photo` / `edit_widget_data` подключены.

**Известные некритичные замечания (G1, не блокируют релиз):**
- Слоистость: `morning_report` (сервис) импортирует `..bot.chart_delivery` (транспорт) — ленивый импорт работает, но нарушает направление зависимостей `bot → services`. Отложить до отдельного рефакторинга.
- `is_period_active` vs `_chart_window` расходятся при `period_start_day=31` в коротких месяцах (2 дня в месяц: первый и последний день «схлопнутого» периода). Исправить через `period_dates` в `is_period_active`.
- Нативный виджет откатан флагом `MONTHLY_WIDGET_ENABLED=False`; ручная проверка в Telegram (iOS/Android/Desktop/Web, тултипы, haptic, 4 КБ zlib) — после возврата виджетов.
- Утренняя рассылка держит DB-сессию во время I/O — вынесено (фикс применён); остаточные места держать под наблюдением.
- `_user_index` в `monthly_summary` keyed только по `telegram_id` (без `chat_id`) — предсуществующее, для лички не проявляется.
- `README.md` дерево проекта не перечисляет `src/assets/fonts/` (runtime-зависимость PNG) — можно добавить при следующем обновлении доков.

### ✅ G2: хранить дневные лимиты каждого дня (2026-11-23)

**Зачем:** карточка и метрики судят день по текущему лимиту, но история не хранится: сверка, добавка дохода и Recovery меняют план, а прошлые дни должны судиться по плану, который действовал тогда.

- Таблица `daily_limits` (`telegram_id`, `plan_date`, `limit`, `source`, `updated_at`), PK `(telegram_id, plan_date)`; `limit` — `plan_today` или Recovery `target`, `source` — `plan` / `recovery`. `ALLOWED_TABLES` обновлён; отдельная миграция не нужна — `init_db()` → `create_all`.
- Запись: `refresh_daily_limit` после коммита мутаций (`save_budget`, `update_budget_field`, `add_income`, `apply_reconciliation`, Recovery create/stop/complete/update), при показе статуса, утреннего отчёта и карточки; плюс джоб 00:05 МСК. Правило — **последнее значение дня побеждает**, прошлые дни не переписываются.
- Гарды: нет активного бюджета, `base_daily_limit <= 0`, `today` вне периода, `days_left <= 0` → снапшот не пишется. `refresh_daily_limit` не бросает исключения в основную логику.
- Backfill прошлых дней — нет (планов не сохраняли); C1 читает снапшоты с fallback на базу.
- [x] ✅ модель + `ALLOWED_TABLES` + `upsert_daily_limit` / `get_daily_limits` (G2a)
- [x] ✅ `get_effective_daily_limit` / `refresh_daily_limit`, триггеры записи, джоб 00:05 (G2b)
- [x] ✅ ADR, `ruff check`, `pytest` (G2c)

### ✅ G2.1: фундамент перед карточкой (2026-11-23)

**Зачем:** C1 — первый потребитель снапшотов. До него закрываем три вещи, которые иначе всплывут уже в видимой карточке.

- **Единый расчёт плана.** `TodayPlan` + `compute_today_plan(telegram_id, budget)` в `budget_service` — единственный канон `spent_period → spent_today → money_for_life_raw → plan_today → base_limit`. Статус и утро считают план один раз и передают его в `refresh_daily_limit`; `get_effective_daily_limit` умеет только «сегодня». Поведение не менялось (G2.1a).
- **Reset не оставляет снапшоты.** `delete_all_budgets` удаляет все `daily_limits` пользователя (сброс = с чистого листа). `delete_active_budget` удаляет строки только за период этого бюджета; та же чистка — для stale-бюджета при смене `period_start_day`. (G2.1b)
- **Гонка upsert.** `upsert_daily_limit` ловит `IntegrityError` только от INSERT, делает `rollback` и повторяет запись как UPDATE (две попытки); ошибка UPDATE и второй конфликт уходят наверх, а `refresh_daily_limit` их глотает. Портируемо для SQLite/PostgreSQL без dialect-specific `ON CONFLICT`. (G2.1c)
- **Тест схемы.** `test_db_schema.py`: созданные таблицы и `Base.metadata` сверяются с `ALLOWED_TABLES`; у `daily_limits` проверены колонки, PK `(telegram_id, plan_date)`, FK на `users` и реальный `IntegrityError` на дубль дня. Это заменяет бессмысленный локальный `schema_audit` на пустом `tratobot.db`.
- Тесты: `test_today_plan.py` (3), `test_daily_limits_cleanup.py` (5), `test_db_schema.py` (3), retry-кейсы в `test_daily_limits.py` (+2). Итог — `738 passed`.

#### ⏳ Отложенная проверка G2.1 — сделать заодно с C1–C3

> Решение пользователя 2026-11-23: коммит `b443c46` (review-фиксы G2.1) запушен **без отдельного повторного @review**, потому что ревью дорогое. Проверить эти места при работе над карточкой, не заводить отдельную задачу.

- [ ] **Одинарный расчёт плана.** Убедиться, что статус и утренний отчёт после `compute_today_plan` → `refresh_daily_limit(..., plan=...)` показывают те же цифры, что до G2.1 (сверить на паре реальных сценариев: обычный день, Recovery, после сверки).
- [ ] **`get_effective_daily_limit` — только «сегодня».** C1 должен читать историю через `get_daily_limits` с fallback на `base_daily_limit`, а не пытаться вызвать эффективный лимит за прошлую дату.
- [ ] **Retry только на INSERT.** Проверить на PostgreSQL-подобной нагрузке (00:05-джоб + статус одновременно), что гонка лечится, а ошибка UPDATE не маскируется повтором.
- [ ] **Границы периода при удалении.** `delete_active_budget` / `_delete_budget_with_limits` для `period_start_day = 29–31` в коротких месяцах: не удаляются ли снапшоты соседнего периода.
- [ ] **SQLite не проверяет FK.** В тестах `PRAGMA foreign_keys` выключен, поэтому порядок удаления `RecoveryState`/`DailyLimit` перед `Budget` проверен только логикой. При C1 либо включить FK в тестовом engine, либо явно прогнать сценарий на PostgreSQL.
- [ ] **Остаточный риск L2.** Если конкурент ещё не закоммитил INSERT, повторная попытка может снова получить `IntegrityError`, и день останется без снапшота (только `warning`). Для C1 это дырка в графике — решить, нужен ли UPDATE-only последний шаг.
- [ ] **Известное, не блокирует:** `morning_report` импортирует aiogram (нарушение слоёв, предсуществующее); `daily_limits` и `budget_service` связаны ленивыми импортами — не делать их модульными без разрыва цикла.

### ✅ C1–C3: Bento-карточка 900×840 (2026-11-23)

**Зачем:** старая карточка 900×620 судила историю по текущему плану и теряла контекст: сколько дней реально в лимите, какая серия, что съело деньги. Новая карточка читает посуточные снапшоты и показывает 4 понятных блока.

- **C1 — данные и метрики.** `MonthlyCardInput` + `compute_card_metrics()`: `daily_limits[]` (снапшот или база), завершённые дни без сегодня, `green/tracked`, скор `70·green/tracked + 30·(1 − overspend/Σlimits)` с гейтом `base > 0`, `tracked ≥ 3`, лиги 55/75/90; серия с нейтральным `0 ₽`; `peak_days` только закрытый, порог 45%, минимальное k ∈ {1,2,3}, гейт `tracked ≥ 7`; `weekend_tax` — доля трат на выходных ≥40% и только при наличии и будней, и выходных; `night_food`/`latte_effect` — ≥15%; `top_expense` — самая дорогая покупка.
- **C2 — рендер.** 900×840, фон `#0B0F14`, карточка `#111822`/`#1E293B`/r16, линия `#1C6CFF` + заливка, ступенчатый пунктир `#FACC15`, перерасход/пик `#FF4433`; шапка с двумя пилюлями; nice-step Y-ось; полая точка сегодня; callout пика одной строкой без категории; bento 2×2 с микро-барами.
- **C3 — лягушки и закрытые состояния.** `src/assets/frogs/{metric_id}.png`, 48×48 RGBA, тихий пропуск при отсутствии, fallback на generic; `quiet_mode_closed` с подписью `за период — ни одной траты`; до старта — `upcoming` без пилюль.
- **Ассеты:** полный набор 25 файлов: `limit_streak_first`, `limit_streak_chasing`, `limit_streak_repeat`, `limit_streak_record`, `limit_streak_zero`, `limit_winrate_clean`, `limit_winrate`, `limit_winrate_rough`, `avg_day`, `bro_score_novice`, `bro_score_own`, `bro_score_pro`, `bro_score_ninja`, `forecast`, `forecast_early`, `top_category`, `top_expense`, `peak_days`, `night_food`, `latte_effect`, `weekend_tax`, `tx_per_day`, `quiet_mode`, `quiet_mode_closed`, `upcoming`.
- **Минимальный набор 16 + 1:** `limit_streak`, `limit_streak_record`, `limit_streak_zero`, `limit_winrate`, `avg_day`, `bro_score`, `forecast`, `top_category`, `top_expense`, `peak_days`, `night_food`, `latte_effect`, `weekend_tax`, `tx_per_day`, `quiet_mode`, `upcoming` (+ `quiet_mode_closed`).
- [x] ✅ C1 — input + метрики + тесты
- [x] ✅ C2 — рендер 900×840 + тесты
- [x] ✅ C3 — лягушки, closed/quiet, доки
- [ ] ⏳ Добавить ассеты лягушек и проверить карточку в Telegram (активный, закрытый, quiet_mode, upcoming)

### G3: Tier 2 — локальные переключатели

Без бэкенда, данные уже в `chat_data`: «По дням» ↔ «Накопительно» (burn-down считается в JS), показ/скрытие линии лимита, призрачный прошлый период — если не перегружает пузырь. Решение о составе — после dogfooding G1.

### G4: Tier 3 — детали дня через бота

Тап по дню → топ-3 категории и крупнейшая трата за день. Требует `allow_queries`, обработчика `widget_query`, `answerWidgetQuery` (ответ ≤ 1 КБ за 15 с, 5 запросов / 5 с, только оригинал в приватном чате). Альтернатива — фильтр истории по дате, отдельная задача. Делать только при реальном запросе «а что было в этот день».

---

## Неделя 2 — AI Insight (отложено)

> ⏸ Отложено решением пользователя 2026-11-15. WeeklyStats готов в локальной ветке `backup-weekly` (`ff4c813`), в `main` не входит.

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