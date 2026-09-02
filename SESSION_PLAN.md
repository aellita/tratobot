# SESSION_PLAN.md — План сессии на 2 недели

> Статус в начале файла. Обновляй в конце каждой сессии: что сделано, что дальше.

---

## 📊 Статус

| Статус | Кол-во задач |
|--------|:------------:|
| ✅ Готово | 22 |
| 🔧 В работе | 0 |
| ⏳ Ожидает | 5 |

**Следующая задача:** День 2 — Задача 2: Rollover-защита

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

- [ ] ⏳ `menu.py:288-311` — `rollover_keep_budget`: показать перенесённые значения в `ROLLOVER_CONFIRMED`

---

### День 3: Проверить daily_limit

> **Цель:** убедиться, что формула корректна на всех этапах периода. Не менять формулу.

- [ ] ⏳ Проверить сценарий 1: income=150000, день 1 → daily_limit=5000, dl_pred=5000
- [ ] ⏳ Проверить сценарий 2: income=150000, трата 2000, день 1 → dl_pred≈5103
- [ ] ⏳ Проверить сценарий 3: период 15-й день, потрачено 75000 → dl_pred=5000
- [ ] ⏳ Проверить сценарий 4: период 15-й день, потрачено 100000 → dl_pred≈3333
- [ ] ⏳ Проверить сценарий 5: последний день периода
- [ ] ⏳ Проверить сценарий 6: переход в новый период
- [ ] ⏳ Новый файл `test_daily_limit_scenarios.py` — 6 параметризованных тестов
- [ ] ⏳ `ruff check` + `ruff format`

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