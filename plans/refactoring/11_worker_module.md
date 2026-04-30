# Plan: Рефакторинг `worker_module` (#10)

> **Статус:** approved  
> **Дата:** 2026-04-09  
> **Исполнитель:** Cursor Composer v2  
> **Ревью:** Claude Opus 4.6  
> **Ссылки:** [00_overview.md](00_overview.md) · [ARCHITECTURE.md §6.10](../../multiprocess_framework/ARCHITECTURE.md)

---

## Context

`worker_module` (#10) — менеджер жизненного цикла потоков-воркеров внутри ProcessModule. Зависит от `base_manager` (#1). Потребитель: `process_module` (#11).

Модуль уже прошёл полный структурный рефакторинг ранее (STATUS.md 8/8). Код в отличном состоянии (~9/10). Текущий рефакторинг — **лёгкий**: документационное выравнивание, исправление ложного ребра в графе зависимостей, создание DECISIONS.md, заполнение §6.10 в глобальном ARCHITECTURE.md.

**Ключевое открытие:** `ARCHITECTURE.md` содержит ребро `worker --> dispatch` (строка 107), но **ни одного импорта dispatch_module в worker_module не существует** (подтверждено grep). WorkerManager — lifecycle manager, не message router. Ребро ошибочное.

**Сложность:** 1/5 — cleanup + documentation, без изменений кода/API.

---

## 1. Текущее состояние

| Метрика | Значение |
|---------|----------|
| Файлов .py (без tests) | 17 |
| LOC (без tests) | 1591 |
| Тест-файлов | 6 |
| Тестов (pytest) | 62 passed |

### Проблемы

| # | Проблема | Серьёзн. | Шаг |
|---|----------|----------|-----|
| P1 | Ложное ребро `worker --> dispatch` в ARCHITECTURE.md (строка 107) | Средняя | 2 |
| P2 | `DOCUMENTATION_SUMMARY.md` дублирует README | Низкая | 1 |
| P3 | `__init__.py` docstring ~105 строк, дублирует README | Низкая | 1 |
| P4 | Нет `DECISIONS.md` для worker_module | Средняя | 3 |
| P5 | §6.10 в ARCHITECTURE.md — TODO-заглушка (строка 445) | Средняя | 4 |
| P6 | Два подхода к конфигу (ThreadConfig + ThreadWorkerConfig) не документированы | Низкая | 3 |

---

## 2. Атомарные шаги

### Шаг 0 — Baseline Audit (read-only) ✅

**Результат:** 62 passed, 17 файлов / 1591 LOC, 0 dispatch-импортов.

---

### Шаг 1 — Удалить DOCUMENTATION_SUMMARY.md, сжать __init__.py docstring (P2, P3)

**Файлы:**
- УДАЛИТЬ `modules/worker_module/DOCUMENTATION_SUMMARY.md`
- ПРАВКА `modules/worker_module/__init__.py` — docstring 105→~18 строк

**Новый docstring (заменить строки 2–105):**
```python
"""
worker_module — менеджер жизненного цикла потоков-воркеров.

Централизованное управление потоками внутри ProcessModule:
создание, запуск, остановка, пауза, мониторинг, перезапуск.

Ключевые компоненты:
    WorkerManager — менеджер (BaseManager + ObservableMixin + IWorkerManager)
    ThreadConfig  — конфигурация потока (Dict at Boundary через to_dict/from_dict)
    WorkerAdapter — адаптер для ProcessModule
    WorkerSchemaAdapter — извлечение настроек из SchemaBase

Типы: WorkerStatus, ThreadPriority, WorkerType, ExecutionMode, WorkerInfo
Интерфейсы: IWorkerManager, IWorkerLifecycle, IWorkerRegistry
SchemaBase-конфиги: ThreadWorkerConfig, WorkerManagerConfig
"""
```

Импорты и `__all__` (строки 107–138) — без изменений.

**Проверка:**
```bash
 && python -m pytest multiprocess_framework/modules/worker_module/tests -v
```

**Коммит:**
```
docs(worker_module): step 1 — remove DOCUMENTATION_SUMMARY.md, trim __init__.py docstring

- Delete DOCUMENTATION_SUMMARY.md (redundant with README.md)
- Compress __init__.py docstring (105 → ~18 lines)

Delta: -1 markdown file, ~-87 LOC docstring

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

### Шаг 2 — Исправить ложное ребро worker→dispatch (P1)

**Файлы:**
- ПРАВКА `multiprocess_framework/ARCHITECTURE.md` строка 107: удалить `    worker --> dispatch`
- ПРАВКА `plans/refactoring/00_overview.md` строка 40: зависимости `#1, #3` → `#1`, обновить фокус рефакторинга

**Действия в ARCHITECTURE.md:**
- Удалить строку 107: `    worker --> dispatch`

**Действия в 00_overview.md:**
- Строка 40, столбец «Зависит от»: `#1, #3` → `#1`
- Строка 40, столбец «Фокус рефакторинга»: `Проверить, что WorkerManager и Dispatcher строятся из одних примитивов. Унифицировать жизненный цикл.` → `Документационное выравнивание. Удалено ложное ребро worker→dispatch (ADR-159). DECISIONS.md, §6.10 в ARCHITECTURE.md.`

**Обоснование:** WorkerManager — менеджер жизненного цикла потоков (create/start/stop/restart). Dispatcher — маршрутизация ключ→обработчик. Ортогональные примитивы. 0 импортов dispatch_module в worker_module. Единственный общий примитив — BaseManager (общий предок).

**Проверка:**
```bash
 && python -m pytest multiprocess_framework/modules/worker_module/tests -v
```

**Коммит:**
```
fix(architecture): step 2 — remove false worker-->dispatch edge from dependency graph

- Remove `worker --> dispatch` from ARCHITECTURE.md mermaid graph (line 107)
- WorkerManager has zero imports from dispatch_module (verified)
- Update 00_overview.md: worker_module depends on #1 only

ADR-159 (created in step 3)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

### Шаг 3 — Создать DECISIONS.md (P4, P6)

**Файлы:**
- СОЗДАТЬ `modules/worker_module/DECISIONS.md`

**Содержимое — 4 ADR:**

```markdown
# worker_module — Архитектурные решения

> Ссылки: [`../../DECISIONS.md`](../../DECISIONS.md) (ADR-008 Dict at Boundary)

## ADR-159: Удаление ложного ребра worker → dispatch

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** ARCHITECTURE.md содержал ребро `worker --> dispatch`, подразумевая, что WorkerManager использует Dispatcher. Grep подтвердил 0 импортов из dispatch_module. WorkerManager — менеджер жизненного цикла потоков (create/start/stop/restart), а не маршрутизатор сообщений. Dispatcher используется в CommandManager и RouterManager для routing ключ→обработчик.  
**Решение:** Удалить ребро из графа. worker_module зависит только от base_manager (#1).  
**Последствия:** Граф зависимостей точнее отражает реальность. Упрощает анализ для process_module (#11).

## ADR-160: Сохранение двух конфигурационных подходов (ThreadConfig + SchemaBase)

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** Модуль имеет два конфигурационных подхода:
1. `core/thread_config.py` — `ThreadConfig` (plain class, `to_dict()`/`from_dict()`) — runtime-объект, используется в WorkerManager/WorkerLifecycle.
2. `configs/thread_worker_config.py` — `ThreadWorkerConfig(SchemaBase)` — Pydantic-схема для декларативного конфига процесса.

STATUS.md явно отмечал: «рантайм ThreadConfig не заменён».  
**Решение:** Сохранить оба. Причины:
- `ThreadConfig` — лёгкий runtime-объект внутри процесса (не пересекает границу процессов сам по себе).
- `ThreadWorkerConfig(SchemaBase)` — декларативная схема для конфигов процесса (`proc_dict["thread"]`), с Pydantic-валидацией.
- Паттерн ADR-008 (Dict at Boundary): Pydantic на границе (`ThreadWorkerConfig.model_dump()` → dict → `ThreadConfig.from_dict()`), plain class внутри.
- Замена ThreadConfig на SchemaBase добавит тяжёлый Pydantic в горячий путь lifecycle без выигрыша.  
**Последствия:** Два объекта с похожими полями, но разными ролями. Документировано.

## ADR-161: Сохранение self.name = manager_name (compatibility alias)

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `worker_manager.py:42` содержит `self.name = manager_name` с комментарием «Синоним для совместимости». Grep показал: используется в `test_worker_manager.py`. Внешних потребителей (process_module) через `.name` не обнаружено.  
**Решение:** Сохранить alias. Причины:
- Минимальная стоимость (1 строка).
- BaseManager может иметь `.name` в будущем (стандартный паттерн).
- Удаление требует правки теста без выигрыша.  
**Последствия:** Alias остаётся. Если BaseManager добавит `.name`, убрать дубликат.

## ADR-162: WorkerInfo как TypedDict (документация) + plain dict (runtime)

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `types/types.py` определяет `WorkerInfo(TypedDict)`, но `registry.register()` конструирует plain dict литерал. TypedDict служит документацией полей, не runtime-проверкой.  
**Решение:** Оставить как есть. TypedDict используется IDE и mypy для подсказок. Runtime-конструкция через dict литерал — стандартный паттерн Python (TypedDict не создаёт экземпляры иначе чем dict).  
**Последствия:** Тип-безопасность обеспечивается IDE/mypy, не runtime.
```

**Проверка:**
```bash
 && python -m pytest multiprocess_framework/modules/worker_module/tests -v
```

**Коммит:**
```
docs(worker_module): step 3 — create DECISIONS.md (ADR-159..162)

- ADR-159: No dispatch_module dependency (lifecycle ≠ routing)
- ADR-160: Dual config (ThreadConfig runtime + ThreadWorkerConfig SchemaBase)
- ADR-161: Keep self.name compatibility alias
- ADR-162: WorkerInfo TypedDict as documentation, plain dict at runtime

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

### Шаг 4 — Заполнить §6.10 в ARCHITECTURE.md, обновить главный DECISIONS.md (P5)

**Файлы:**
- ПРАВКА `multiprocess_framework/ARCHITECTURE.md` строка 445: заменить TODO-заглушку на полное описание (~30 строк)
- ПРАВКА `multiprocess_framework/DECISIONS.md` после строки 1846: добавить строку worker_module

**Содержимое §6.10 (заменить строку `### 6.10 \`worker_module\` — *TODO (после модуля #10)*`):**

```markdown
### 6.10 `worker_module` — управление потоками-воркерами

**Роль:** Централизованное управление жизненным циклом потоков внутри ProcessModule: создание, запуск, остановка, пауза, мониторинг, перезапуск. Зависит только от base_manager (#1).

**WorkerManager** (BaseManager + ObservableMixin, ~231 LOC) — фасад: делегирует WorkerRegistry (хранение) и WorkerLifecycle (создание/запуск/остановка потоков).
**WorkerAdapter** (~138 LOC) — тонкая обёртка для ProcessModule.
**WorkerSchemaAdapter** (~94 LOC) — извлечение настроек потока из SchemaBase-конфигов.

```
WorkerManager(BaseManager, ObservableMixin, IWorkerManager)
    ├── create_worker() / start / stop / restart / pause / resume
    ├── _worker_registry: WorkerRegistry (threading.Lock, Dict[str, WorkerInfo])
    ├── _lifecycle: WorkerLifecycle (create thread, start, stop, auto-restart)
    ├── ThreadConfig (runtime) — to_dict/from_dict (Dict at Boundary)
    └── ThreadWorkerConfig(SchemaBase) — декларативный конфиг (Pydantic)
```

Два режима выполнения:
- **LOOP** — бесконечный цикл, stop_event для остановки. Финальный статус: STOPPED.
- **TASK** — одноразовое выполнение. Финальный статус: COMPLETED.

Два типа воркеров: **SYSTEM** (фреймворк, e.g. message_processor), **APPLICATION** (пользовательский).

Ключевые решения (ADR-159…162):
- **Нет зависимости от dispatch_module:** WorkerManager — lifecycle manager, не message router (ADR-159).
- **Dual config:** ThreadConfig (runtime) + ThreadWorkerConfig (SchemaBase) — осознанное разделение (ADR-160).

📖 [`modules/worker_module/README.md`](modules/worker_module/README.md) · [`modules/worker_module/DECISIONS.md`](modules/worker_module/DECISIONS.md)
```

**Строка в главный DECISIONS.md (после строки 1846 с router_module):**
```
| `worker_module` | [`modules/worker_module/DECISIONS.md`](modules/worker_module/DECISIONS.md) | Command & Work | ADR-159…162 (нет зависимости от dispatch, dual config, self.name alias, WorkerInfo TypedDict) |
```

**Проверка:**
```bash
 && python -m pytest multiprocess_framework/modules/worker_module/tests -v
```

**Коммит:**
```
docs(worker_module): step 4 — fill ARCHITECTURE.md §6.10, update global DECISIONS.md index

- ARCHITECTURE.md §6.10: WorkerManager architecture, lifecycle modes, key ADRs
- Main DECISIONS.md: add worker_module row (ADR-159..162)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

### Шаг 5 — Финальная валидация и обновление метрик

**Файлы:**
- ПРАВКА `modules/worker_module/STATUS.md` — строка в историю версий
- ПРАВКА `plans/refactoring/00_overview.md` строка 95 — заполнить `files_after`, `loc_after`, `tests_after`

**Обновление STATUS.md** — добавить строку в таблицу «История версий»:
```
| 1.1 | Apr 9, 2026 | ✅ Systematic refactoring | Документационное выравнивание: DECISIONS.md (ADR-159..162), §6.10 ARCHITECTURE.md, удалено ложное ребро worker→dispatch |
```

**Обновление 00_overview.md строка 95:**
```
| 10 | `worker_module`              |  17   |  1591  |   6   |  TODO  | TODO | 17 | ~1506 | 6 (62 passed) |
```

**Проверка (полная):**
```bash
 && python -m pytest multiprocess_framework/modules/worker_module/tests -v
 && python -m pytest multiprocess_framework/modules/process_module/tests -v
 && python scripts/run_framework_tests.py
```

**Коммит:**
```
refactor(worker_module): step 5 — final validation, update STATUS.md and 00_overview.md

- Source files: 17 (unchanged), LOC: 1591 → ~1506
- Tests: 6 files, 62 passed, no regressions
- Removed false worker-->dispatch edge, created DECISIONS.md (ADR-159..162)
- Filled §6.10 in ARCHITECTURE.md

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

## 3. Целевые метрики

| Метрика | До | После |
|---------|-----|-------|
| Файлов .py (без tests) | 17 | 17 |
| LOC .py (без tests) | 1591 | ~1506 |
| Тестов | 62 passed | 62 passed |
| Ребро worker→dispatch | есть (ложное) | удалено |
| DECISIONS.md | нет | ADR-159…162 |
| ARCHITECTURE.md §6.10 | TODO | заполнено |

---

## 4. Что НЕ делать

1. **НЕ** заменять ThreadConfig на SchemaBase — осознанное решение (ADR-160)
2. **НЕ** удалять `self.name` alias — стоимость 1 строка, используется в тестах (ADR-161)
3. **НЕ** менять публичный API — process_module не затрагивается
4. **НЕ** добавлять dispatch_module интеграцию — WorkerManager не маршрутизатор (ADR-159)
5. **НЕ** менять thread-safety в WorkerLifecycle — GIL + daemon, формальный fix сложен без выигрыша
6. **НЕ** удалять configs/ пакет — используется для декларативного конфига
7. **НЕ** менять тесты — 62/62 зелёные

---

## 5. Кросс-модульные изменения

| Модуль | Файл | Изменение |
|--------|------|-----------|
| worker_module | `DOCUMENTATION_SUMMARY.md` | УДАЛИТЬ |
| worker_module | `__init__.py` | Сжать docstring |
| worker_module | `DECISIONS.md` | СОЗДАТЬ |
| worker_module | `STATUS.md` | Обновить |
| multiprocess_framework | `ARCHITECTURE.md` | Удалить worker→dispatch (строка 107), §6.10 (строка 445) |
| multiprocess_framework | `DECISIONS.md` | Строка worker_module (после строки 1846) |
| plans/refactoring | `00_overview.md` | Строка #10 (строки 40, 95) |

---

## 6. Definition of Done

- [x] `DOCUMENTATION_SUMMARY.md` удалён
- [x] `__init__.py` docstring ≤ 20 строк
- [x] Ребро `worker --> dispatch` удалено из ARCHITECTURE.md
- [x] `00_overview.md` строка #10: зависимость `#1` (без `#3`)
- [x] `DECISIONS.md` создан (ADR-159…162)
- [x] `ARCHITECTURE.md` §6.10 заполнен
- [x] Главный `DECISIONS.md` содержит строку worker_module
- [x] `00_overview.md` метрики after заполнены
- [x] 62 тестов worker_module passed
- [x] Тесты process_module passed (нет регрессий)

---

## 7. Ключевые файлы

```
multiprocess_framework/
├── ARCHITECTURE.md                          ← строка 107 (удалить edge), строка 445 (§6.10)
├── DECISIONS.md                             ← после строки 1846 (индекс)
└── modules/worker_module/
    ├── __init__.py                          ← сжать docstring (шаг 1)
    ├── DOCUMENTATION_SUMMARY.md             ← УДАЛИТЬ (шаг 1)
    ├── DECISIONS.md                         ← СОЗДАТЬ (шаг 3)
    └── STATUS.md                            ← обновить (шаг 5)

plans/refactoring/
├── 00_overview.md                           ← строки 40, 95
└── 11_worker_module.md                      ← этот план
```
