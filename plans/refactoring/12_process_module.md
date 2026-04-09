# Plan: Рефакторинг `process_module` (#11)

> **Статус:** done  
> **Дата:** 2026-04-09  
> **Исполнитель:** Cursor Composer v2  
> **Ревью:** Claude Opus 4.6  
> **Ссылки:** [00_overview.md](plans/refactoring/00_overview.md) · [ARCHITECTURE.md §6.11](Inspector_prototype/multiprocess_framework/ARCHITECTURE.md)

---

## Context

`process_module` (#11) — центральный модуль фреймворка. Собирает worker, router, logger, command, config, shared_resources в единый `ProcessModule` — базовый класс, от которого наследуются **19+ процессов** (7 в prototype v1, 6 в v2, 4 template, ProcessManagerProcess).

Все зависимости (#2, #5, #8, #9, #10) уже отрефакторены. Модуль в хорошем состоянии (~8.5/10), но `process_module.py` (585 LOC) содержит init-код, который логичнее живёт в `ProcessLifecycle`, а также мёртвый код и backward-compat alias.

**Цель из 00_overview.md:** "Сжать `process_module.py` (585 LOC): 6 субкомпонентов → 3–4."

**Сложность:** 2/5 — хирургические перемещения + удаление мёртвого кода + документация. **Публичный API НЕ меняется.**

---

## 1. Текущее состояние

| Метрика | Значение |
|---------|----------|
| Файлов .py (без tests) | 27 |
| LOC (без tests) | ~2704 |
| Тест-файлов | 6 |
| Тестов (pytest) | 69 passed |
| process_module.py LOC | 585 |

### Проблемы

| # | Проблема | Серьёзн. | Шаг |
|---|----------|----------|-----|
| P1 | `_init_configuration` (20 LOC) + `_init_queues` (34 LOC) в process_module.py — вызываются ТОЛЬКО из ProcessLifecycle | Средняя | 1 |
| P2 | `state/process_state_registry.py` — backward-compat alias, 0 импортёров | Средняя | 2 |
| P3 | `ProcessManagers.initialize()` 210 LOC монолит — 7 менеджеров + 6 адаптеров | Средняя | 3 |
| P4 | Нет `DECISIONS.md` | Средняя | 4 |
| P5 | §6.11 в ARCHITECTURE.md — TODO | Средняя | 4 |
| P6 | `reload_manager()` — заглушка, 0 вызовов | Низкая | 5 |
| P7 | `__import__` вместо `importlib.import_module` | Низкая | 5 |

---

## 2. Атомарные шаги

### Шаг 0 — Baseline (read-only)

```bash
cd Inspector_prototype && python -m pytest multiprocess_framework/modules/process_module/tests -v
find multiprocess_framework/modules/process_module -name "*.py" ! -path "*/tests/*" ! -path "*/__pycache__/*" -exec wc -l {} + | sort -rn
```

---

### Шаг 1 — Перенести `_init_configuration` + `_init_queues` в ProcessLifecycle

**Файлы:**
- ПРАВКА `lifecycle/process_lifecycle.py` — добавить `_init_configuration()` и `_init_queues()` как приватные методы. В `initialize()` заменить `self.process._init_configuration()` → `self._init_configuration()`, аналогично для queues
- ПРАВКА `core/process_module.py` — удалить `_init_configuration()` (строки 139–159) и `_init_queues()` (строки 161–194). Убрать `from multiprocessing import Queue` из импортов (строка 9)

**Детали переноса в process_lifecycle.py:**

`_init_configuration()`: создаёт ProcessConfigHandler, ConfigManager, связывает их. Добавить lazy imports:
```python
from ..configs import ProcessConfigHandler
from ...config_module import ConfigManager
```

`_init_queues()`: получает очереди из ProcessData или создаёт дефолтные. Добавить import:
```python
from multiprocessing import Queue
```

В `initialize()` (строки 38–41):
```python
# Было:
self.process._init_configuration()
self.process._init_queues()
# Стало:
self._init_configuration()
self._init_queues()
```

**Проверка:**
```bash
cd Inspector_prototype && python -m pytest multiprocess_framework/modules/process_module/tests -v
```

**Коммит:**
```
refactor(process_module): step 1 — move _init_configuration + _init_queues into ProcessLifecycle

- Move _init_configuration() (20 LOC) to process_lifecycle.py
- Move _init_queues() (34 LOC) to process_lifecycle.py
- Called ONLY from ProcessLifecycle.initialize(), now local
- Public API unchanged — methods were private (_)

Delta: process_module.py 585 → ~530 LOC

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

### Шаг 2 — Удалить backward-compat alias `state/process_state_registry.py`

**Файлы:**
- УДАЛИТЬ `state/process_state_registry.py` (12 LOC, 0 импортёров — подтверждено grep)
- ПРАВКА `state/__init__.py` — убрать `from .process_state_registry import ProcessStateRegistry` (строка 9) и `'ProcessStateRegistry'` из `__all__`

**Оставить** `state/process_data.py` — используется в `data_schema_module/storage/storage_manager.py` (TYPE_CHECKING).

**Проверка:**
```bash
cd Inspector_prototype && python -m pytest multiprocess_framework/modules/process_module/tests -v
cd Inspector_prototype && python -m pytest multiprocess_framework/modules/data_schema_module/tests -v --tb=short
```

**Коммит:**
```
refactor(process_module): step 2 — remove process_state_registry backward-compat alias

- Delete state/process_state_registry.py (0 external importers, confirmed by grep)
- Keep state/process_data.py (used by data_schema_module TYPE_CHECKING)
- Update state/__init__.py exports

Delta: -1 file, -12 LOC

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

### Шаг 3 — Расслоить `ProcessManagers.initialize()` на подметоды

**Файлы:**
- ПРАВКА `managers/process_managers.py`

**Действия:** Разбить 210-LOC `initialize()` на:
```python
def initialize(self):
    managers_config = self.process.config_handler.get_managers_config()
    self._create_worker_manager()
    self._create_logger_manager(managers_config)
    self._create_error_manager(managers_config)
    self._create_router_manager(managers_config)
    self._create_stats_manager(managers_config)
    self._create_command_manager(managers_config)
    self._create_console_manager(managers_config)
    self._register_all_managers()
    self._attach_all_adapters()
    self._connect_event_manager()
```

Каждый `_create_*_manager()` содержит ровно ту логику, которая была в соответствующем блоке `initialize()`. Lazy imports остаются в каждом методе.

Также удалить `reload_manager()` (строки 219–226) — заглушка, 0 вызовов.

**Проверка:**
```bash
cd Inspector_prototype && python -m pytest multiprocess_framework/modules/process_module/tests -v
```

**Коммит:**
```
refactor(process_module): step 3 — decompose ProcessManagers.initialize() into pipeline

- Extract _create_worker_manager(), _create_logger_manager(), etc.
- Extract _register_all_managers() and _attach_all_adapters()
- Remove reload_manager() stub (0 callers, no implementation)
- initialize() reads as clear pipeline

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

### Шаг 4 — Документация: DECISIONS.md, §6.11, глобальный индекс

**Файлы:**
- СОЗДАТЬ `modules/process_module/DECISIONS.md` — 5 ADR (163–167)
- ПРАВКА `ARCHITECTURE.md` строка 474 — заполнить §6.11
- ПРАВКА `DECISIONS.md` — строка process_module после worker_module

**ADR-163:** Dual Communication API (send_message legacy vs send extended) — сохранить оба, разные возвраты (bool vs Dict).
**ADR-164:** ISharedResources Protocol для DI — нет циклических зависимостей.
**ADR-165:** Удаление backward-compat alias process_state_registry (0 импортёров).
**ADR-166:** ProcessManagers.initialize() декомпозиция на pipeline подметодов.
**ADR-167:** `importlib.import_module` вместо `__import__` в _create_workers_from_config.

**§6.11:** ProcessModule = BaseManager + ObservableMixin + IProcessModule. Делегация: ProcessLifecycle, ProcessManagers, ProcessCommunication, ProcessState, SystemThreads. Dual communication API. ISharedResources Protocol.

**Строка в главный DECISIONS.md:**
```
| `process_module` | [`modules/process_module/DECISIONS.md`](modules/process_module/DECISIONS.md) | Process | ADR-163…167 (dual comm API, ISharedResources DI, compat alias removal, managers decomposition, importlib) |
```

**Коммит:**
```
docs(process_module): step 4 — create DECISIONS.md (ADR-163..167), fill §6.11

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

### Шаг 5 — Удалить мёртвый код, заменить __import__

**Файлы:**
- ПРАВКА `core/process_module.py`

**Действия:**

1. **Удалить `reload_manager()`** (строки 440–442) — 0 вызовов, заглушка.

2. **Заменить `self.log()` в `run()` и `stop()`:**
   - Строка 539: `self.log("INFO", ...)` → `self._log_info(f"Process '{self.name}' started", module="lifecycle")`
   - Строка 545: `self.log("INFO", ...)` → `self._log_info(f"Process '{self.name}' stopping", module="lifecycle")`

3. **Заменить `__import__` на `importlib.import_module`** в `_create_workers_from_config()`:
   ```python
   import importlib
   module = importlib.import_module(module_path)
   ```

4. **Пометить `log()` deprecated** в docstring (метод используется в тесте, не удаляем).

**Коммит:**
```
refactor(process_module): step 5 — remove dead code, replace __import__ with importlib

- Remove reload_manager() stub (0 callers)
- Replace self.log() calls with self._log_info() in run()/stop()
- Replace __import__ with importlib.import_module
- Mark log() as deprecated

Delta: process_module.py ~530 → ~520 LOC

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

### Шаг 6 — Финальная валидация и обновление метрик

**Файлы:**
- ПРАВКА `STATUS.md` — строка 1.1 в историю версий
- ПРАВКА `00_overview.md` строка 96 — `files_after`, `loc_after`, `tests_after`

**Обновление:**
```
| 11 | `process_module`             |  27   |  2704  |   6   |  TODO  | TODO | 26 | ~2645 | 6 (69 passed) |
```

**Проверка (полная):**
```bash
cd Inspector_prototype && python -m pytest multiprocess_framework/modules/process_module/tests -v
cd Inspector_prototype && python -m pytest multiprocess_framework/modules/worker_module/tests -v
cd Inspector_prototype && python scripts/run_framework_tests.py
```

**Коммит:**
```
refactor(process_module): step 6 — final validation, update STATUS.md and 00_overview.md

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

## 3. Целевые метрики

| Метрика | До | После |
|---------|-----|-------|
| Файлов .py (без tests) | 27 | 26 |
| LOC .py (без tests) | ~2704 | ~2645 |
| process_module.py | 585 | ~520 |
| Тестов | 69 passed | 69 passed |
| ProcessManagers.initialize() | 210 LOC монолит | pipeline из подметодов |
| DECISIONS.md | нет | ADR-163…167 |
| §6.11 | TODO | заполнено |

---

## 4. Что НЕ делать

1. **НЕ** менять публичный API ProcessModule — IProcessModule контракт, 19+ наследников
2. **НЕ** удалять `log()` — тестируется, может использоваться в подклассах
3. **НЕ** удалять `state/process_data.py` — используется в data_schema_module
4. **НЕ** объединять 6 logging override методов — менять ObservableMixin вне скоупа
5. **НЕ** удалять dual communication API — осознанное решение (ADR-163)
6. **НЕ** трогать ProcessCommunication/SystemThreads/ProcessState — стабильный код
7. **НЕ** менять тесты — 69/69 зелёные

---

## 5. Кросс-модульные изменения

| Модуль | Файл | Изменение |
|--------|------|-----------|
| process_module | `core/process_module.py` | Удалить init methods, reload_manager; importlib; deprecated log() |
| process_module | `lifecycle/process_lifecycle.py` | Добавить _init_configuration, _init_queues |
| process_module | `managers/process_managers.py` | Расслоить initialize(); удалить reload_manager |
| process_module | `state/process_state_registry.py` | УДАЛИТЬ |
| process_module | `state/__init__.py` | Убрать ProcessStateRegistry |
| process_module | `DECISIONS.md` | СОЗДАТЬ (ADR-163..167) |
| process_module | `STATUS.md` | Обновить |
| multiprocess_framework | `ARCHITECTURE.md` | §6.11 (строка 474) |
| multiprocess_framework | `DECISIONS.md` | Строка process_module |
| plans/refactoring | `00_overview.md` | Строка #11 |

---

## 6. Definition of Done

- [x] `_init_configuration` и `_init_queues` — тело в ProcessLifecycle; тонкие делегаты на ProcessModule (ADR-166a), вызов из lifecycle через `process._*` для совместимости с тестами
- [x] `state/process_state_registry.py` удалён
- [x] `ProcessManagers.initialize()` декомпозирован
- [x] `reload_manager()` удалён
- [x] `__import__` → `importlib.import_module`
- [x] `self.log()` → `self._log_info()` в run()/stop()
- [x] `DECISIONS.md` создан (ADR-163…167 + ADR-166a)
- [x] `ARCHITECTURE.md` §6.11 заполнен
- [x] Главный `DECISIONS.md` содержит process_module
- [x] `00_overview.md` метрики after заполнены
- [x] 69 тестов process_module passed
- [x] Тесты worker_module passed (нет регрессий)

---

## 7. Ключевые файлы

```
Inspector_prototype/multiprocess_framework/
├── ARCHITECTURE.md                              ← строка 474 (§6.11)
├── DECISIONS.md                                 ← индекс
└── modules/process_module/
    ├── core/process_module.py                   ← удалить init methods, reload, importlib (шаги 1,5)
    ├── lifecycle/process_lifecycle.py            ← добавить init methods (шаг 1)
    ├── managers/process_managers.py              ← расслоить initialize(), удалить reload (шаг 3)
    ├── state/process_state_registry.py           ← УДАЛИТЬ (шаг 2)
    ├── state/__init__.py                        ← обновить (шаг 2)
    ├── DECISIONS.md                             ← СОЗДАТЬ (шаг 4)
    └── STATUS.md                                ← обновить (шаг 6)

plans/refactoring/
├── 00_overview.md                               ← строка 96
└── 12_process_module.md                         ← этот план
```
