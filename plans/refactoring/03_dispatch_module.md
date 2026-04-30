# Refactoring plan: `dispatch_module` (модуль #3)

> **Статус:** 🟡 Ожидает выполнения.  
> **Автор плана:** Opus, Фаза 1 мета-плана v4.1.  
> **Исполнитель:** Cursor Composer Agent (Agent mode / Composer 2).  
> **Ссылки:** [00_overview.md](./00_overview.md) · [ARCHITECTURE.md](../../multiprocess_framework/ARCHITECTURE.md)

---

## 0. Контекст

Модуль **уже прошёл рефакторинг** (STATUS.md: 8/8, оценка 9/10). Стратегии вынесены в `strategies/`. Однако `core/dispatcher.py` остаётся **736 LOC** — три ответственности в одном классе:

1. **Dispatch routing** (выбор стратегии, поиск handler, вызов) — ~240 LOC
2. **Scenario management** (CRUD + dispatch_scenario) — ~165 LOC  
3. **Handler lifecycle** (register, update*, overwrite, query) — ~165 LOC
4. **Backward compat** (old params: `logger_manager=`, `error_manager=`, `statistics_manager=`, `self.handlers`, `self.name`, `AdvancedDispatcher` alias) — ~80 LOC

**Цель:** Dispatcher остаётся фасадом, но сценарии выносятся в отдельный файл, backward compat удаляется. Результат: ~450 LOC dispatcher.py (−39%).

**Внешние потребители (3 модуля):**
- `channel_routing_module/core/channel_routing_manager.py` — `from ...dispatch_module import Dispatcher, DispatchStrategy`
- `command_module/core/command_manager.py` — `from ...dispatch_module import Dispatcher, DispatchStrategy`
- `logger_module/core/log_dispatcher.py` — `from ...dispatch_module import Dispatcher, DispatchStrategy`

Все создают `Dispatcher(manager_name, ...)`. Нужно проверить, использует ли кто-то старый API (`logger_manager=` и т.д.).

---

## 1. Текущее состояние (baseline)

- **Файлов:** 17 `.py` (без tests/__pycache__)
- **LOC:** 2 243
- **Тестов:** 4 файла (test_dispatcher 408 LOC, test_scenario_builder 180, test_strategies 245, test_types 195)
- **Статус тестов:** все зелёные (STATUS: 56 тестов)
- **Публичный API (`__init__.py`):** `Dispatcher`, `BaseDispatcher`, `DispatchStrategy`, `HandlerInfo`, `Scenario`, `ScenarioBuilder`, `IDispatcher`, `DispatcherConfig`, `AdvancedDispatcher` (alias)

### 1.1. Структура dispatcher.py (736 LOC) — карта для split

```
Строки   | Блок                          | Куда?
---------|-------------------------------|------------------
1-31     | Импорты                       | dispatcher.py
33-68    | Docstring класса              | dispatcher.py
70-158   | __init__ (incl. backward compat) | dispatcher.py (−30 LOC compat)
160-163  | @property scenarios            | dispatcher.py
169-218  | initialize() / shutdown()      | dispatcher.py
224-248  | _get_strategy_from_message()   | dispatcher.py
250-315  | register_handler()             | dispatcher.py
317-329  | _find_handler_in_strategy()    | dispatcher.py
331-365  | _find_handler()                | dispatcher.py
367-466  | dispatch()                     | dispatcher.py
470-485  | create_scenario()              | → scenarios.py
487-492  | delete_scenario()              | → scenarios.py
494-498  | get_scenario_info()            | → scenarios.py
500-502  | get_all_scenarios()            | → scenarios.py
504-527  | add_handler_to_scenario()      | → scenarios.py
529-533  | remove_handler_from_scenario() | → scenarios.py
535-539  | reorder_handler_in_scenario()  | → scenarios.py
541-546  | update_scenario_metadata()     | → scenarios.py
548-553  | update_scenario_description()  | → scenarios.py
555-632  | dispatch_scenario()            | → scenarios.py
636-664  | update_handler_*() × 5        | dispatcher.py (тонкие делегаты)
666-693  | overwrite_handler()            | dispatcher.py
695-707  | get_handler_info()             | dispatcher.py
709-721  | get_all_handlers()             | dispatcher.py
723-735  | get_handlers_by_tag()          | dispatcher.py
```

---

## 2. Целевая структура

```
dispatch_module/
├── __init__.py                    # API (без AdvancedDispatcher alias)
├── interfaces.py                  # IDispatcher (без изменений)
├── README.md                      # Обновлён
├── STATUS.md                      # Обновлён
├── DECISIONS.md                   # НОВЫЙ (ADR-130…132)
├── types/
│   ├── __init__.py
│   └── types.py                   # Без изменений
├── core/
│   ├── __init__.py
│   ├── base_dispatcher.py         # Без изменений
│   ├── dispatcher.py              # ~450 LOC (−39%): фасад без scenario-методов
│   └── scenarios.py               # НОВЫЙ: ~180 LOC, ScenarioManager class
├── strategies/                    # Без изменений (уже разделены)
│   ├── __init__.py
│   ├── base_strategy.py
│   ├── exact_match.py
│   ├── pattern_match.py
│   ├── fallback_match.py
│   └── chain_match.py
├── builders/
│   ├── __init__.py
│   └── scenario_builder.py        # Без изменений
├── configs/
│   ├── __init__.py
│   └── dispatcher_config.py       # Без изменений
└── tests/
    ├── test_dispatcher.py         # Обновлён (убраны тесты old API)
    ├── test_scenarios.py          # НОВЫЙ: тесты ScenarioManager
    ├── test_scenario_builder.py
    ├── test_strategies.py
    └── test_types.py
```

---

## 3. Атомарные шаги

### ⚠️ ВАЖНО для Composer

Этот рефакторинг отличается от предыдущих:
- **data_schema_module** — удаление мёртвых файлов (безопасно).
- **dispatch_module** — **расщепление живого класса** (рискованно).

**Правила:**
1. После КАЖДОГО шага: `pytest multiprocess_framework/modules/dispatch_module/tests -v`
2. НЕ менять сигнатуры публичных методов `Dispatcher` (кроме удаления backward compat params).
3. Все 10 методов scenario-группы (`create_scenario`, `delete_scenario`, ..., `dispatch_scenario`) переносятся в `ScenarioManager`, а на `Dispatcher` остаются **тонкие делегаты** (1-2 строки каждый), чтобы НЕ ломать публичный API.

---

### Шаг 0 — Baseline ⬜

1. `pytest dispatch_module/tests -v` — записать число тестов.
2. Проверить, какие внешние потребители используют old API:
   ```
   grep -rn "logger_manager=" --include="*.py" modules/{channel_routing,command,logger}_module/
   grep -rn "error_manager=" --include="*.py" modules/{channel_routing,command,logger}_module/
   grep -rn "statistics_manager=" --include="*.py" modules/{channel_routing,command,logger}_module/
   grep -rn "AdvancedDispatcher" --include="*.py" modules/
   grep -rn "\.handlers\b" --include="*.py" modules/{channel_routing,command,logger}_module/
   ```
3. Записать результаты — кто использует old API.
4. Коммит: `docs(dispatch_module): baseline audit`.

---

### Шаг 1 — Извлечь ScenarioManager в `core/scenarios.py` ⬜

**Что создать:** Новый файл `core/scenarios.py` с классом `ScenarioManager`.

```python
# core/scenarios.py
"""Управление сценариями (CHAIN_MATCH) для Dispatcher."""

from typing import Dict, Any, Callable, Optional, List
from ..types.types import HandlerInfo, Scenario


class ScenarioManager:
    """
    Менеджер сценариев — CRUD + выполнение цепочек обработчиков.
    
    Используется внутри Dispatcher как композиция (не наследование).
    """
    
    def __init__(self):
        self._scenarios: Dict[str, Scenario] = {}
    
    @property
    def scenarios(self) -> Dict[str, Scenario]:
        return self._scenarios
    
    def has_scenario(self, name: str) -> bool:
        return name in self._scenarios
    
    # Сюда переносятся ВСЕ 10 методов из dispatcher.py:
    # create_scenario()        — строки 470-485
    # delete_scenario()        — строки 487-492
    # get_scenario_info()      — строки 494-498
    # get_all_scenarios()      — строки 500-502
    # add_handler_to_scenario() — строки 504-527
    # remove_handler_from_scenario() — строки 529-533
    # reorder_handler_in_scenario()  — строки 535-539
    # update_scenario_metadata()     — строки 541-546
    # update_scenario_description()  — строки 548-553
    # dispatch_scenario()      — строки 555-632
    
    def clear(self):
        """Очистить все сценарии (для shutdown)."""
        self._scenarios.clear()
```

**Что изменить в `dispatcher.py`:**
1. В `__init__`: заменить `self._scenarios: Dict[str, Scenario] = {}` на `self._scenario_mgr = ScenarioManager()`.
2. Все 10 scenario-методов заменить **тонкими делегатами**:
   ```python
   def create_scenario(self, name, description="", metadata=None):
       return self._scenario_mgr.create_scenario(name, description, metadata)
   
   def dispatch_scenario(self, scenario_name, message, data_field="data", stop_on_error=True):
       return self._scenario_mgr.dispatch_scenario(scenario_name, message, data_field, stop_on_error)
   
   # ... аналогично для остальных 8
   ```
3. В `dispatch()` (строки 404, 412-417, 423-434): заменить `self._scenarios` на `self._scenario_mgr.scenarios` или `self._scenario_mgr.has_scenario(key)`.
4. В `_find_handler()` (строка 357): `if key in self._scenarios` → `if self._scenario_mgr.has_scenario(key)`.
5. В `shutdown()` (строка 206): `self._scenarios.clear()` → `self._scenario_mgr.clear()`.
6. Property `scenarios` (строка 161): делегировать `return self._scenario_mgr.scenarios`.

**Тесты:** Все существующие тесты должны пройти **без изменений** (делегаты сохраняют API).

Коммит: `refactor(dispatch_module): extract ScenarioManager into core/scenarios.py`.

---

### Шаг 2 — Удалить backward compat из `__init__` ⬜

**Что удалить из `Dispatcher.__init__` (строки 78-85, 108-124, 133-134, 155-156):**

```python
# УДАЛИТЬ эти параметры из сигнатуры __init__:
logger_manager: Optional[Any] = None,      # строка 79
error_manager: Optional[Any] = None,       # строка 80
statistics_manager: Optional[Any] = None,  # строка 81
enable_logging: bool = True,               # строка 82
enable_error_tracking: bool = True,        # строка 83
enable_statistics: bool = True,            # строка 84

# УДАЛИТЬ блок обратной совместимости (строки 108-124):
if managers is None:
    managers = {}
    if logger_manager:
        managers['logger'] = logger_manager
    ...

if config is None:
    config = {
        'logger': enable_logging,
        ...
    }

# УДАЛИТЬ (строки 133-134):
self.name = manager_name  # Для обратной совместимости
self.strategy = default_strategy  # Для обратной совместимости

# УДАЛИТЬ (строки 155-156):
self.handlers = self._handlers_storage[DispatchStrategy.EXACT_MATCH]
```

**Что удалить из `register_handler` (строки 299-301):**
```python
# УДАЛИТЬ:
if result and target_strategy == DispatchStrategy.EXACT_MATCH:
    self.handlers = self._handlers_storage[DispatchStrategy.EXACT_MATCH]
```

**Целевая сигнатура `__init__`:**
```python
def __init__(
    self,
    manager_name: str,
    process: Optional["Process"] = None,
    default_strategy: DispatchStrategy = DispatchStrategy.EXACT_MATCH,
    managers: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
    config_manager: Optional[Any] = None,
    **kwargs
):
```

**Проверить внешних потребителей:**
- Если grep из Шага 0 показал, что кто-то использует `logger_manager=` → **сначала мигрировать потребителя** на `managers={'logger': ...}`.
- Если grep показал использование `.handlers` или `.name` → мигрировать.

**Тесты:** Обновить `test_dispatcher.py` — убрать тесты backward compat API. Добавить тест, что старые параметры НЕ принимаются (TypeError).

Коммит: `refactor(dispatch_module): remove backward compat API (logger_manager=, etc.)`.

---

### Шаг 3 — Удалить `AdvancedDispatcher` alias ⬜

1. В `__init__.py`: удалить строку `AdvancedDispatcher = Dispatcher` и из `__all__`.
2. Grep: `grep -rn "AdvancedDispatcher" --include="*.py" ` — если кто-то использует, заменить на `Dispatcher`.
3. Тесты зелёные.
4. Коммит: `refactor(dispatch_module): remove AdvancedDispatcher alias`.

---

### Шаг 4 — Создать `tests/test_scenarios.py` ⬜

Создать отдельный тест-файл для `ScenarioManager`:

```python
# tests/test_scenarios.py
"""Тесты ScenarioManager (извлечён из Dispatcher)."""
from dispatch_module.core.scenarios import ScenarioManager

class TestScenarioManager:
    def test_create_scenario(self): ...
    def test_delete_scenario(self): ...
    def test_add_handler_to_scenario(self): ...
    def test_dispatch_scenario_success(self): ...
    def test_dispatch_scenario_stop_on_error(self): ...
    def test_dispatch_scenario_passes_result_between_stages(self): ...
    def test_scenario_not_found(self): ...
    def test_clear(self): ...
```

Эти тесты тестируют `ScenarioManager` **напрямую**, без Dispatcher. Существующие тесты в `test_dispatcher.py` продолжают тестировать через делегаты.

Коммит: `test(dispatch_module): add direct ScenarioManager tests`.

---

### Шаг 5 — Документация ⬜

#### 5.1. `DECISIONS.md` (новый)

```markdown
# dispatch_module — Архитектурные решения

## ADR-130: Извлечение ScenarioManager из Dispatcher
Сценарии (CRUD + dispatch_scenario) вынесены в `core/scenarios.py`.
Dispatcher хранит ScenarioManager через композицию и делегирует вызовы.

## ADR-131: Удаление backward compat API
Параметры `logger_manager=`, `error_manager=`, `statistics_manager=` удалены.
Используйте `managers={'logger': ..., 'error': ..., 'statistics': ...}`.

## ADR-132: Удаление AdvancedDispatcher alias
`AdvancedDispatcher` был alias на `Dispatcher`. Удалён — используйте `Dispatcher`.
```

#### 5.2. README.md — обновить

- Убрать секции про backward compat API.
- Добавить в структуру `core/scenarios.py`.

#### 5.3. STATUS.md — обновить

- Дата, фаза 9/9, упомянуть split.

#### 5.4. ARCHITECTURE.md §6.3 — заполнить

Заполнить по образцу §6.1 (≤ 100 строк): роль, диаграмма, ссылка на README.

#### 5.5. Главный DECISIONS.md

Добавить строку в таблицу «Модульные решения».

Коммит: `docs(dispatch_module): add DECISIONS.md, update README, fill ARCHITECTURE.md §6.3`.

---

### Шаг 6 — Финальная валидация ⬜

1. `pytest dispatch_module/tests -v` — зелёные.
2. `python scripts/validate.py` — зелёный.
3. `python scripts/run_framework_tests.py` — все зелёные.
4. Собрать метрики «после».
5. Обновить `plans/refactoring/00_overview.md` — строка `dispatch_module`.
6. Коммит: `refactor(dispatch_module): final validation and metrics`.

---

## 4. Ключевые решения

### 4.1. Почему ScenarioManager, а не ScenarioMixin

Mixin потребовал бы изменения MRO (`class Dispatcher(BaseManager, ObservableMixin, ScenarioMixin)`) и возможные конфликты `__init__`. Композиция (`self._scenario_mgr = ScenarioManager()`) проще, тестируемее, не меняет наследование.

### 4.2. Почему делегаты на Dispatcher, а не удаление scenario-методов

Публичный API Dispatcher включает `create_scenario`, `dispatch_scenario` и т.д. Три модуля используют `Dispatcher`. Удаление методов — breaking change. Делегаты (1-2 строки) сохраняют API, а реальная логика в `ScenarioManager`.

### 4.3. Почему НЕ выносить handler update/query в отдельный класс

5 методов `update_handler_*` — по 3-4 строки каждый, чистые делегаты к стратегиям. `overwrite_handler` — 28 строк. `get_handler_info/all/by_tag` — по 10-13 строк. Суммарно ~100 LOC. Выносить в отдельный класс — overengineering для 100 строк однотипного кода.

---

## 5. Что НЕ делать Composer-у

1. **НЕ** менять файлы в `strategies/` — они уже чистые.
2. **НЕ** менять `base_dispatcher.py` — он lightweight, отдельная сущность.
3. **НЕ** менять `types/types.py` — типы стабильны.
4. **НЕ** менять `builders/scenario_builder.py` — он использует `Dispatcher` через публичный API.
5. **НЕ** менять внешние модули (channel_routing, command, logger) **если** grep из Шага 0 не показал использование old API. Если показал — мигрировать только те строки.
6. **НЕ** удалять docstrings из Dispatcher — они полезны.
7. **НЕ** добавлять новые фичи или абстракции.

---

## 6. Подсказки для Composer

### Паттерн делегата (повторить для всех 10 методов):
```python
# В dispatcher.py — ПОСЛЕ извлечения
def create_scenario(self, name: str, description: str = "", metadata: Dict[str, Any] = None) -> bool:
    """Создать новый сценарий."""
    return self._scenario_mgr.create_scenario(name, description, metadata)
```

### Замена `self._scenarios` в dispatch():
```python
# БЫЛО:
if explicit_scenario and explicit_scenario in self._scenarios:
# СТАЛО:
if explicit_scenario and self._scenario_mgr.has_scenario(explicit_scenario):
```

### Замена в _find_handler():
```python
# БЫЛО:
if key in self._scenarios:
# СТАЛО:
if self._scenario_mgr.has_scenario(key):
```

---

## 7. Definition of Done (модуль #3)

- [ ] `core/scenarios.py` создан, `ScenarioManager` работает.
- [ ] `dispatcher.py` ≤ 500 LOC (цель ~450).
- [ ] Backward compat API удалён (`logger_manager=`, `error_manager=`, `statistics_manager=`, `self.handlers`, `self.name`, `self.strategy`).
- [ ] `AdvancedDispatcher` alias удалён.
- [ ] Все тесты `dispatch_module` зелёные.
- [ ] Все внешние потребители (3 модуля) — тесты зелёные.
- [ ] `validate.py` зелёный.
- [ ] `DECISIONS.md` создан (ADR-130…132).
- [ ] Главный `DECISIONS.md` обновлён.
- [ ] ARCHITECTURE.md §6.3 заполнен.
- [ ] Метрики «после» в `00_overview.md`.
- [ ] `tests/test_scenarios.py` создан.

---

## 8. Целевые метрики

| Метрика | До | После (цель) |
|---------|-----|--------------|
| `dispatcher.py` LOC | 736 | ~450 (−39%) |
| Файлов (без tests) | 17 | 18 (+1: scenarios.py) |
| Общий LOC | 2 243 | ~2 200 (−2%, за счёт удаления compat) |
| Тестов | 4 файла | 5 файлов (+test_scenarios) |
| Публичный API | 9 экспортов | 8 (−AdvancedDispatcher) |

---

## 9. Также: заполнить ARCHITECTURE.md §6.2 для data_schema_module

> **Пропущено Composer-ом при рефакторинге data_schema_module.** Заполнить по образцу §6.1:

Содержимое для вставки вместо строки `### 6.2 data_schema_module — *TODO (после модуля #2)*`:

```markdown
### 6.2 `data_schema_module` — ядро данных

**Роль:** Независимое ядро для описания структур данных на базе Pydantic v2. Нулевые зависимости от других модулей фреймворка.

**`SchemaBase`** (`RegisterBase`) — базовый класс для регистров. Наследник Pydantic `BaseModel` с дополнительными возможностями: `FieldMeta` (UI-метаданные, валидация, ограничения), `FieldRouting` (канал Router, process_targets), `RegisterDispatchMeta` (цели доставки для всего регистра).

**`SchemaMixin`** (`RegisterMixin`) — 5 ключевых методов для работы с полями: `build()` → `(manager_name, model_dump())` для Dict at Boundary.

```
SchemaBase (Pydantic v2 BaseModel)
    ├── FieldMeta          — дескриптор поля (min/max, UI-подсказки)
    ├── FieldRouting        — канал Router + process_targets
    └── RegisterDispatchMeta — цели доставки для регистра

SchemaRegistry             — реестр схем (без Singleton)
DataConverter / FileStorage — сериализация: dict/JSON/YAML
RegistersContainer         — контейнер состояния регистров
```

Ключевые решения (ADR-120…123):
- Удалён `_compat.py` (0 внешних потребителей).
- Удалены shim-директории (`fields/`, `utils/` re-exports).
- `extensions/` — только явный импорт, не входит в top-level API.

📖 Подробнее: [`modules/data_schema_module/README.md`](modules/data_schema_module/README.md)
```

**Это можно сделать в рамках Шага 5 dispatch_module (вместе с заполнением §6.3).**
