# Карта фраз Тратобота — техническая карта системы сообщений

> Источник: `tratobot/src/utils/phrases.py` (839 строк, 365 Assign, 364 уникальных константы, 1 дубль `NEW_CATEGORY_PROMPT` ×2) + 19 точек импорта `phrases.` в `src/bot/handlers/*.py` и `src/services/*.py`. Не меняет код и тексты — только фиксирует, когда и как каждая фраза показывается.
> Полная таблица: `docs/PHRASE_TABLE.csv` (фильтр по `scenario`, `status`, `user_facing`).

---

## Краткая карта 11 сценариев

### 1. Добавление траты
- **Сценарий:** свободный ввод `500 кофе`, `500+300 такси`, мультилайн, FSM `AddExpense.waiting_for_amount`, вечерний `EveningState.filling`.
- **Вход:** `@router.message()` `handle_text` / `process_expense` / `handle_evening_expense`, `parse_multi_expense_text()` → `ExpenseParseReport`.
- **Условия:** `is_valid`, `was_corrected` (скобки/хвостовой знак), `MATH_ERROR`, `spent_today > dl_pred`, `duplicateMiddleware` (`new/warn/silent`).
- **Фразы:** `EXPENSE_SAVED_LINE`, `EXPENSE_SAVED_ALL`, `ERR_MATH_CORRECTED`, `ERR_MATH_ERROR` (`ERR_NEGATIVE_RESULT/ZERO_RESULT/DIV_BY_ZERO`), `STATUS_BIG_SPEND`, `FALLBACK_DESC`, `DEFAULT_CATEGORY`, `DUP_*`, `EVENING_SAVED/LINE_*`.
- **Ветки:** `was_corrected → SAVED_LINE + CORRECTED + BTN_FIX_AMOUNT`; `MATH_ERROR → ERR_MATH_ERROR + retry`; `big_spend → " 🚨"`; `duplicate warn → DUP_WARNING + BTN_DUP_*`, `silent → drop`, `confirm → DUP_CONFIRMED`, `del → DUP_DELETED`.

### 2. Утренний отчёт (08:00 MSK, `send_morning_reports`)
- **Вход:** `cron[08:00 MSK]` → `for tg_id` → `UserSettings.notifications_enabled` → `Monthly Summary` ветка (period_end+1) → `get_active_budget` → `money_for_life/dl_pred/pct_*`.
- **Условия:** `today == period_end+1 → rollover`, `budget==None → skip`, `end_of_period (days<=3)`, `money_for_life`, `pct_pred >80 / >=51 / >=26`, `pct_sim >80 / >=51 / >=26`, `yesterday_spent <= dl_pred`, `RECOVERY_ENABLED`.
- **Фразы:** `MORNING_GREETING`, `MORNING_TODAY_PLAN`, `YESTERDAY_OK/OVER`, `ZONE_END_EMPTY_1/2`, `ZONE_END_OK_1/2`, `ZONE_GREEN_1/2`, `ZONE_YELLOW_LIGHT_1/2`, `MORNING_YELLOW_SIM_GREEN_1/2`, `MORNING_YELLOW_SIM_BLUE_1/2`, `MORNING_YELLOW_SIM_NONE_1/2`, `MORNING_RED_SIM_GREEN_1/2`, `MORNING_RED_SIM_BLUE_1/2`, `MORNING_RED_SIM_YELLOW_1/2`, `MORNING_RED_DEAD_1/2`, `ROLLOVER_OFFER`, плюс Recovery `RECOVERY_SUCCESS/DAILY_ACTIVE/DAILY_OFFER` + `BTN_RECOVERY_*`.
- **Ветки:** см. дерево MORNING ниже. Выбор `random.choice(2)` в каждой зоне, `BTN_RECALC_LIMIT` vs `USE_SAVINGS_*` vs `FRESH_START` по `zone`.

### 3. Вечерний отчёт (22:00 teaser, 23:30 auto-close, `get_evening_message` + `evening_flow.finalize`)
- **Вход:** `limit = available_cash/days_left`, `spent = today_sum`, `available_cash = total_available - period_spent`.
- **Условия:** `spent==0 → ZERO_1-3`, `spent<=limit → GREEN_1-4`, `spent>limit → OVER_1-3` (`overdraft`, `days_to_grease`), `current_state != EveningState.filling → EVENING_TIMEOUT`, `EXPENSE_SIMPLE_CHECK`.
- **Фразы:** `EVENING_INITIAL/CONTAINER`, `EVENING_ZERO_1-3`, `EVENING_GREEN_1-4`, `EVENING_OVER_1-3`, `EVENING_TIMEOUT`, `EVENING_SAVED/LINE_*`, `AUTO_CLOSE` (5), плюс Recovery `RECOVERY_EVENING_HEADER/SAVED/EXACT/GOOD/SHORTENED/FORECAST/SLIGHT/HEAVY`.
- **Ветки:** см. дерево EVENING. Вечер `recalculate_days` → `10→8` честно, прогноз только `+`.

### 4. Статус / Daily Limit (`_build_status`)
- **Вход:** `menu_status` callback / `BTN_DAILY_LIMIT` reply → `_build_status` → `days_left`, `dl_pred/dl_simulated`, `pct_pred/sim`, `remaining_today`, `spent_today`, `Recovery` блок.
- **Условия:** `budget==None → NO_BUDGET`, `end_of_period`, `pct_pred >80/>=51/>=26`, `pct_sim`, `remaining_today>0`, `spent_today>dl_pred`, `budget.mandatory/savings/wishlist_amount` (скрытие нулей), `RECOVERY_ENABLED`.
- **Фразы:** `STATUS_ZONE_ATAS/FINISH/IN_LIMIT/CAN_MORE/ON_EDGE/CRITICAL`, `STATUS_REMAINING_FREE/ZERO`, `STATUS_SPENT`, `STATUS_RESERVES_HEADER`, `STATUS_BALANCE_TITLE/TODAY_TITLE/PERIOD_TITLE/REMAINING_PERIOD`, `STATUS_FOOTER_END_EMPTY_1-3`, `END_OK_1-3`, `GREEN_1-3`, `YELLOW_LIGHT_1-3`, `YELLOW_CUBBY_GREEN/BLUE`, `YELLOW_NONE_1-3`, `RED_CUBBY_GREEN/BLUE/YELLOW`, `RED_DEAD_1-3`, плюс Recovery `RECOVERY_DAILY_ACTIVE/OFFER`.
- **Ветки:** зеркало утренней, но `footer` 3 варианта + `sim` ветки.

### 5. Recovery (временный режим поверх `Budget.daily_limit`)
- **Вход:** `B = resolve_frozen_baseline(budget)` frozen, `trigger 0.85`, `days+7<=remaining`, `60/70/80%`, `success 0.90`, `small 1.10`, `cooldown 3д / 0.5*B`.
- **Условия:** `B<1000 → block`, `dl_pred > B*0.85 → []`, `deficit<=0 → []`, `days+7>remaining → invalid`, `dismissed + should_repeat_offer`, `active + check_success`, `is_small_overspend`, `recalculate_days`.
- **Фразы:** `RECOVERY_OFFER_TITLE/BASELINE/OPTION_LINE/TAIL_LINE`, `OFFER_SINGLE/MULTI`, `DISMISSED/CHOSEN/STOPPED`, `DAILY_ACTIVE/OFFER`, `EVENING_HEADER/SAVED/EXACT/GOOD/SHORTENED/FORECAST/SLIGHT/HEAVY`, `SUCCESS`, `BUDGET_DONE/SHORTENED`, `PERIOD_END`, `BTN_RECOVERY_FAST/BALANCED/SOFT/TRY/DISMISS/PLAN/STOP`.
- **Ветки:** см. дерево RECOVERY. Утро — решение, вечер — факт, `target` стабилен, `total_days` мутирует.

### 6. Monthly Report (Rich HTML, `format_summary_text`)
- **Вход:** `build_summary_data` → `total_spent`, `available`, `pct`, `top_cat`, `totem` via `TOTEM_MAP` substring, `active` период, `breakdown`.
- **Условия:** `available<=0 → ⚪ Нет данных`, `pct<=70 → 🟢 Зелёная / <=90 🔵 / <=100 🟡 / else 🔴`, `active → EGG_TOTEM` else totem phrase, `breakdown empty → MONTHLY_EMPTY`.
- **Фразы:** `MONTHLY_HEADER/IN_PROGRESS/EGG_TOTEM`, `MONTHLY_ZONE_TAG/GREEN/BLUE/YELLOW/RED/NO_DATA`, `MONTHLY_TOTAL_SPENT/BUDGET_LABEL/AVG_DAY/TOP_HEADER/TABLE_CAPTION/COL_*/TOTAL_LABEL/ROUNDING_LABEL/PERIOD_LABEL/DETAILS_SUMMARY`, `MONTHLY_TOTEM_TRAVEL/FOOD/SHOPPING/FUN/HEALTH/HOME/DEFAULT`, `MONTHLY_NO_CATEGORY`, `DEFAULT_CATEGORY`.
- **Ветки:** `pct` зоны + `active` яйцо vs totem + `rounding_total>0`.

### 7. Duplicate Expenses (`DuplicateMiddleware`)
- **Вход:** `check(user_id, amount, desc)` → `new/warn/silent` (15s окно, 3 эскалации, `message_id` защита).
- **Фразы:** `DUP_WARNING`, `DUP_CONFIRMED`, `DUP_DELETED`, `BTN_DUP_DEL/CONFIRM`, `BALANCE_UNKNOWN`, `FALLBACK_DESC`.
- **Ветки:** `new → save`, `warn → DUP_WARNING + keyboard (early return)`, `silent → drop`, `pending confirm → DUP_CONFIRMED + balance` or `del → DUP_DELETED`.

### 8. Onboarding (`BudgetSetup` 2 шага)
- **Вход:** `/start` → `not user → seed categories + ONBOARDING_START` / `user → WELCOME_BACK + RESTART`, `BudgetSetup.waiting_for_income → waiting_for_period_start → _finish_onboarding`.
- **Фразы:** `ONBOARDING_START/RESTART`, `PERIOD_START_CHOICE/CUSTOM_PROMPT`, `ONBOARDING_PERIOD_DONE/MANDATORY_PROMPT/WISHLIST_PROMPT/ROUNDING_PROMPT`, `BUDGET_COMPLETE/STATUS_BUDGET_COMPLETE`, `ONBOARDING_HINT_SETTINGS`, `ONBOARDING_INCOME_ACCEPTED`, `PERIOD_UPDATED`, `GREETINGS` (3), `WELCOME_MENU/BACK`, `ERR_INVALID_NUMBER/TOO_MANY_RETRIES`, `BTN_SKIP/CANCEL/BACK`.
- **Ветки:** FSM `income → period (Today/1-е/Другое → 1-31 clamp) → _finish_onboarding (saves budget + UserSettings rounding)`. `REPLY_MENU_COMMANDS` interrupt → `FSM_INTERRUPT_PERIOD`.

### 9. Rollover (`period_end+1` morning + `NewPeriodSetup`)
- **Вход:** `today == period_end+1` → `send_rich_message` summary + `bot.send_message ROLLOVER_OFFER` с `get_rollover_keyboard`.
- **Фразы:** `ROLLOVER_OFFER`, `ROLLOVER_CONFIRMED`, `ROLLOVER_WITH_DETAILS`, `ROLLOVER_CARRIED_MANDATORY/SAVINGS/WISHLIST`, `ROLLOVER_KEEP_DATE_PROMPT`, `ROLLOVER_ASK_INCOME`, `ERR_ROLLOVER_NOT_FOUND`, `BTN_ROLLOVER_KEEP/EDIT/KEEP_INCOME/KEEP_DATE`, `DEFAULT_WISHLIST_NAME`.
- **Ветки:** `if carried_parts → WITH_DETAILS else CONFIRMED`; `keep → expire old recovery + save_budget(free_money=0)`, `edit → NewPeriodSetup income → date → _finish_new_period (copy mandatory/black_day/wishlist)`.

### 10. Ошибки (валидация, retry, глобальный)
- **Фразы:** `ERR_GENERIC/DB/INVALID_NUMBER/TOO_MANY_RETRIES/EXPENSE_SAVE/NOT_FOUND/DELETE_FAILED/RESTORE_FAILED`, `ERR_CATEGORY_EXISTS/NOT_FOUND/NAME_LENGTH`, `ERR_VOICE/MEDIA/PARSE/EMPTY/MATH_ERROR/CORRECTED/NEGATIVE/ZERO/DIV_BY/MISSING/CANNOT_PARSE`, `HINT_TRAILING/CLOSED/REMOVED/DOUBLE/JUNK`, `ERR_WISHLIST_EMPTY/NO_BUDGET/REPORT_FAILED/ROVER_NOT_FOUND/SAVINGS_EMPTY`, plus `_shared.handle_invalid_input` funnel.
- **Ветки:** `try parse_amount → ERR_INVALID_NUMBER + check_retry(3) → ERR_TOO_MANY_RETRIES + state.clear + get_main_menu_keyboard`, `MATH_ERROR → detail + 3 retry`, `was_corrected → ERR_MATH_CORRECTED + BTN_FIX_AMOUNT`.

### 11. Категории
- **Фразы:** `CATEGORY_MANAGEMENT_TITLE/LIST_ACTIVE/ARCHIVED/EMPTY/DETAIL_HEADER/ARCHIVED_NOTE`, `CATEGORY_RENAME_PROMPT/RENAMED/ARCHIVED/UNARCHIVED`, `CATEGORY_DELETE_WARNING/MOVE_PROMPT/DELETED_MOVED/HARD/CONFIRM_PROMPT`, `CATEGORY_NOT_FOUND`, `CATEGORY_PICKER/CHANGED/CREATED`, `BTN_CATEGORY_RENAME/ARCHIVE/UNARCHIVE/DELETE/*`, `BTN_MANAGE_CATEGORIES`, `DEFAULT_CATEGORY`, `ERR_CATEGORY_*`, `NEW_CATEGORY_PROMPT`.
- **Ветки:** `list → active/archived + is_archived suffix`, `detail → archived note if is_archived`, `rename → build_category_name + duplicate/len check`, `archive toggle`, `delete → 0 count → hard? else warning → move/hard/confirm`.

---

## Подробные деревья ветвлений (реальные условия из кода)

### MORNING REPORT (`morning_report.py:173-357`, `491` строк)
```
send_morning_reports (cron 08:00 MSK)
├── for tg_id in users
│   ├── if _has_morning_report_today → continue
│   ├── if UserSettings.notifications_enabled == False → continue
│   ├── if today == period_end+1 (get_period_dates) → Monthly Summary + ROLLOVER_OFFER + expire recovery + _log_morning_report → continue
│   ├── budget = get_active_budget (this_month vs last_month by period_start_day)
│   │   └── if not budget or daily_limit<=0 → continue
│   ├── compute: days_left, dl_pred, dl_simulated, pct_pred/sim, money_for_life, end_of_period (days<=3), yesterday_spent, overdraft
│   ├── yesterday_line:
│   │   ├── if yesterday_spent <= dl_pred → YESTERDAY_OK {spent,limit}
│   │   └── else → YESTERDAY_OVER {spent,limit,over}
│   ├── zone / btn_type:
│   │   ├── if end_of_period and money<=0 → END_EMPTY (ZONE_END_EMPTY_1/2 random) → FRESH_START [RECALC_LIMIT]
│   │   ├── elif end_of_period → END_OK (ZONE_END_OK_1/2) → REGULAR
│   │   ├── elif pct_pred >80 → GREEN (ZONE_GREEN_1/2) → REGULAR
│   │   ├── elif pct_pred >=51 → YELLOW_LIGHT (ZONE_YELLOW_LIGHT_1/2) → REGULAR
│   │   ├── elif pct_pred >=26:
│   │   │   ├── if pct_sim >80 → YELLOW_SIM_GREEN (MORNING_YELLOW_SIM_GREEN_1/2) → FROM_YELLOW_TO_GREEN
│   │   │   ├── elif pct_sim >=51 → YELLOW_SIM_BLUE (MORNING_YELLOW_SIM_BLUE_1/2) → FROM_YELLOW_TO_BLUE
│   │   │   └── else → YELLOW_SIM_NONE (MORNING_YELLOW_SIM_NONE_1/2) → REGULAR
│   │   └── else: # pct<26 RED
│   │       ├── if pct_sim >80 → RED_SIM_GREEN (MORNING_RED_SIM_GREEN_1/2) → FROM_RED_TO_GREEN
│   │       ├── elif pct_sim >=51 → RED_SIM_BLUE (1/2) → FROM_RED_TO_BLUE
│   │       ├── elif pct_sim >=26 → RED_SIM_YELLOW (1/2) → FROM_RED_TO_YELLOW
│   │       └── else → RED_DEAD (1/2) → FRESH_START
│   ├── full_text = MORNING_GREETING + MORNING_TODAY_PLAN{limit} + yesterday_line + zone_text
│   └── Recovery (if RECOVERY_ENABLED):
│       ├── if active:
│       │   ├── if check_success(dl_pred, baseline) 0.90 → complete("success") + RECOVERY_SUCCESS {baseline}
│       │   └── else → RECOVERY_DAILY_ACTIVE {cur,total,target,days,baseline,tail} + [STOP]
│       └── elif !active:
│           ├── b=resolve_frozen_baseline, opts=calculate_recovery_options(B,money,days)
│           ├── if opts and should_repeat_offer → RECOVERY_DAILY_OFFER {dl_pred} + [PLAN]
│           └── else → no recovery block
```

### EVENING REPORT (`evening_report.py:47-76` + `evening_flow.py:139-178` + `auto-close 149-343`)
```
get_evening_message(limit, spent, available_cash, days_left)
├── if spent <= limit:
│   ├── saved = limit - spent
│   ├── if int(spent)==0 → random.choice(EVENING_ZERO_1{limit}, ZERO_2, ZERO_3)
│   └── else → random.choice(EVENING_GREEN_1{limit,spent,saved}, GREEN_2{limit,spent}, GREEN_3{limit,spent}, GREEN_4{spent,saved})
└── else: # spent>limit
    ├── overdraft = spent - limit
    ├── days_to_grease = int(available_cash/overdraft) clamp 1..days_left
    └── random.choice(EVENING_OVER_1{over,days}, OVER_2{over,days_left}, OVER_3{over,min(5,days_left)})

finalize_evening_report(limit=available_cash/days_left)
├── if limit<=0 → ERR_REPORT_FAILED
├── else → get_evening_message → callback.answer + kb (BACK_MAIN if not EXPENSE_SIMPLE_CHECK)

send_auto_close_reports (23:30):
├── if current_state != EveningState.filling → TIMEOUT if not evening else continue
├── total = today_sum, recovery_extra = RECOVERY_EVENING_HEADER/SAVED/EXACT/... (if active, recalculate_days, shortened vs saved/overspend, forecast if saved>0 and sim_days<total)
└── bot.send_message(random.choice(AUTO_CLOSE).format(total) + recovery_extra)

Teaser (22:00): INITIAL_TEXT + quote "> Сегодня, {date}:" + expense_lines → EVENING_CONTAINER / INITIAL_TEXT
```

### STATUS (`menu.py:492-742`)
```
_build_status
├── if not budget → NO_BUDGET
├── compute: days_left, dl_base, savings, money_for_life, dl_pred/sim, pct_pred/sim, end_of_period, remaining_today, spent_today, wishlist_amount
├── zone: same as morning but 6 labels STATUS_ZONE_ATAS/FINISH/IN_LIMIT/CAN_MORE/ON_EDGE/CRITICAL
├── today: if remaining_today>0 → STATUS_REMAINING_FREE else ZERO; spent_line = STATUS_SPENT + " ⚠️" if spent>dl_pred
├── reserves: mandatory? RESERVE_MANDATORY, savings? RESERVE_SAVINGS, wishlist? RESERVE_WISHLIST → header RESERVES_HEADER else hide
├── text = BALANCE_TITLE · emoji label + TODAY + PERIOD_TITLE + REMAINING_PERIOD + reserves + recovery_block
├── footer/btns: mirror morning but 3-way random for footers (END_EMPTY_1-3, END_OK_1-3, GREEN_1-3, YELLOW_LIGHT_1-3, YELLOW_CUBBY_*, RED_*)
└── kb = _build_status_keyboard(btn_type) + recovery_kb_extra (PLAN/STOP) merged
```

### RECOVERY (`recovery_service.py:43-81` + handlers)
```
calculate_recovery_options(B, money, days)
├── if B<1000 or B==0 → []
├── if days<=0 → []
├── dl_pred = money/days; if dl_pred > B*0.85 → []
├── deficit = B*days - money; if <=0 → []
└── for ratio 0.60/0.70/0.80:
    ├── target = (B*ratio).quantize(1)
    ├── days = ceil(deficit/(B-target)); if None → skip
    └── if days+7 <= days → append (tail = days_remaining - days)

Morning/Status offer: if dismissed and last_offer_at: days_since = today - last_offer_at; cur_deficit; if !should_repeat_offer(last+0.5*B or >=3d) → hide
Active: cur_day = today - started_at +1; tail = days_left - total_days; check_success 0.90 → complete
Evening: saving_today = max(0,target-spent); new_days = ceil(deficit/(B-target)); if new!=old → update; forecast sim_deficit+saved
Budget hook: if success → complete(budget_update)+RECOVERY_BUDGET_DONE; elif new_days+7>days → period_end; elif new<old → SHORTENED
```

### MONTHLY REPORT (`monthly_report.py:208-322`)
```
available = income - mandatory - black_day
if available<=0 → ⚪ NO_DATA
elif pct<=70 → 🟢 GREEN / <=90 🔵 BLUE / <=100 🟡 YELLOW / else 🔴 RED
Totem: first trigger substring in cat_lower → TOTEM_MAP else Чебурашка
Header: MONTHLY_HEADER + IN_PROGRESS if active
Body: ZONE_TAG, TOTAL_SPENT, BUDGET_LABEL, AVG_DAY, if breakdown: TOP_HEADER, TABLE_CAPTION/COL_*, TOTAL_LABEL, ROUNDING_LABEL if >0, DETAILS + PERIOD_LABEL if label, DETAILS_SUMMARY <details>
```

### DUPLICATE (`DuplicateMiddleware`)
```
check(amount,desc, message_id):
├── if message_id already seen → silent (Telegram retry)
├── if last same amount+desc within 15s:
│   ├── count==1 → warn → DUP_WARNING + BTN_DUP_DEL/CONFIRM (early return)
│   └── count>=2 → silent
└── else → new → save + DUP_CONFIRMED / record
```

---

## Итоговая статистика (из `PHRASE_TABLE.csv`)

- **Всего констант:** 365 Assign (364 уникальных, 1 дубль `NEW_CATEGORY_PROMPT` ×2 строки 158 и 182)
- **Реально используется (`USED`):** 339 (93%)
- **Не используется (`UNUSED`):** 24 (7%) — преимущественно `STATUS_PERIOD_*` старые (`STATUS_PERIOD_NEGATIVE/POSITIVE/ZERO`, `STATUS_REMAINING_OK/STOP`), `ROUND_UP`, `REDUCE_LIMIT_ACCEPTED`, `HINT_*` внутренние, `PERIOD_SET_PERIOD`, часть `BTN_*` без handler (`BTN_RESTART_BUDGET` в start_choice но используется — помечен USED)
- **Дубли:** 1 (`NEW_CATEGORY_PROMPT` идентичный текст, статус `DUPLICATE` ×2 строки, фактически 1 фраза)
- **Неоднозначных (`UNCLEAR`):** 0 после выноса (`TODO` в morning закрыты), ранее 7 `MORNING_YELLOW/RED` были `UNCLEAR` до P0
- **Много вариантов (≥2):** 12 групп: `GREETINGS` 3, `AUTO_CLOSE` 5, `ZONE_END_*` 2, `ZONE_GREEN_*` 2, `MORNING_YELLOW/RED_*` 2 каждая (7 групп ×2 =14), `EVENING_ZERO_*` 3, `EVENING_GREEN_*` 4, `EVENING_OVER_*` 3, `STATUS_FOOTER_*` 3 каждая (10 групп ×3 =30), `MONTHLY_TOTEM_*` 7 totems
- **Практически без вариативности:** `RECOVERY` (1 строка на ветку, выбор условный, не random), `HISTORY_EMPTY` (1), `CATEGORY_*` (1), `ROLLOVER_*` (1)

**Каналы (`user_facing`):**
- `message` 260, `button` 75, `error` 29, `internal` 5 (`DEFAULT_CATEGORIES`, `MENU_KEYWORDS`, `HINT_*`, `FALLBACK_DESC`)

---

## Что обнаружено (проблемы/аномалии)

- **Дубли:** `NEW_CATEGORY_PROMPT` 2 определения (строки 158 и 182) — одинаковый текст, мёртвая строка 182 (перезаписывает 158, без эффекта).
- **Почти одинаковые тексты:** `STATUS_FOOTER_YELLOW_CUBBY_GREEN` vs `MORNING_YELLOW_SIM_GREEN_1` (оба `Кубышка ... вернёт в зелень`), `EVENING_GREEN_1` vs `EVENING_GREEN_3` (оба `лимит {limit}, факт {spent}`) — разные сценарии, один смысл, стоит унифицировать тон.
- **Мёртвые фразы (UNUSED 24):** `STATUS_PERIOD_NEGATIVE/POSITIVE/ZERO`, `STATUS_REMAINING_OK/STOP` (заменены на `REMAINING_FREE/ZERO + SPENT`), `ROUND_UP` (legacy округление, флаг off), `HINT_JUNK_CHARS` (не используется — только 4 других HINT), `BTN_ROUNDING_*` (UI скрыт), `PERIOD_SET_PERIOD` (не вызывается).
- **Одна фраза — много сценариев:** `BTN_BACK_MAIN` используется в 8 местах (morning, evening, status, categories), `ERR_INVALID_DATA` в 6, `NO_BUDGET` в 3 — нормально, но усложняет A/B тест.
- **Выбор альтернативы:** везде `random.choice(list)` без весов, не `по условию` — равновероятно, не зависит от `pct` внутри зоны.

## Что нужно будет сделать на следующем этапе (без правок сейчас)

1. **Удалить дубль** `NEW_CATEGORY_PROMPT` (оставить 1, проверить `categories.py:223` и `menu.py:1497` оба используют один).
2. **Пометить UNUSED как deprecated** — `STATUS_PERIOD_*` 3, `ROUND_UP`, `HINT_JUNK_CHARS` — удалить или скрыть из CSV `user_facing=internal`.
3. **Унифицировать footers** — `STATUS_FOOTER_YELLOW_CUBBY_*` vs `MORNING_YELLOW_SIM_*` — вынести общий `CUBBY_GREEN_1/2` или оставить как 2 сценария с разным контекстом (утро vs статус) — решить.
4. **Добавить весовые `random`** — если нужна вариативность не 50/50 (например, `EVENING_GREEN_1` чаще), заменить `random.choice` на `random.choices(weights)`.
5. **Подготовить редакторский бэклог** — для каждой `STATUS_FOOTER_*` (3 варианта) и `MORNING_*` (2) собрать 3–5 вариантов tone-of-voice без изменения условий (как в ТЗ Recovery A-P уже 1 строка → расширить).
6. **Проверить `user_facing=internal`** — скрыть из редактуры `DEFAULT_CATEGORIES`, `MENU_KEYWORDS`, `DEFAULT_CATEGORY` tuple.
