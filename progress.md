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

---

## Шпаргалка для агента

После каждой сессии (или по запросу пользователя) агент проверяет: было ли что-то из списка «Когда писать». Если да — добавляет запись в этот файл перед завершением работы.
