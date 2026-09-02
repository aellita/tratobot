# SESSION_PLAN.md — План сессии на 2 недели

> Статус в начале файла. Обновляй в конце каждой сессии: что сделано, что дальше.

---

## 📊 Статус

| Статус | Кол-во задач |
|--------|:------------:|
| ✅ Готово | 33 |
| 🔧 В работе | 0 |
| ⏳ Ожидает | 4 |

**Следующая задача:** День 4 — B18 + ASAP-дубликат + E501

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

### День 4: B18 + ASAP-дубликат + E501

> **Цель:** закрыть технический хвост.

- [ ] ⏳ B18: `morning_report.py` — `budget.free_money - spent_period` → `budget.free_money`
- [ ] ⏳ ASAP-дубликат: `expense_service.py` — `get_today_expenses_grouped`: если `desc == cat_name`, не дублировать
- [ ] ⏳ E501: `phrases.py` — разбить 18 длинных строк
- [ ] ⏳ `ruff check` + `ruff format`
- [ ] ⏳ `pytest` — полный прогон

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