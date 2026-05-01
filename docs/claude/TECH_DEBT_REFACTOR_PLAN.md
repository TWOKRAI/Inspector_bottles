# План: устранение технических долгов фреймворка

## Context

Ревью архитектуры выявило 4 категории долгов:
1. **Standalone-модули** (`state_store_module`, `chain_module`, `registers_module`) не используют `BaseManager + ObservableMixin`, хотя содержат классы-менеджеры. Следствие: их логи не идут через `logger_module`, нарушая единый observability-канал.
2. **Прямой `import logging` / `from loguru import logger`** в ~34 файлах вместо фреймворкового `_log_info()`.
3. **PyQt5 в документации** — миграция завершена, но 3 документа всё ещё пишут PyQt5.
4. **MODULE_CONTRACTS.md** не покрывает `chain_module` и `state_store_module`; STATUS.md `chain_module` устарел.

Цель: привести фреймворк к единому стандарту, чтобы новый модуль не нуждался в отдельной конвенции.

---

## Фаза 1 — BaseManager + ObservableMixin для менеджеров (6 классов)

### 1.1 `StateStoreManager`

**Файл:** `modules/state_store_module/manager/state_store_manager.py`

Текущее состояние:
```python
class StateStoreManager(IStateStoreManager):
    def __init__(self, router=None, initial_state=None, logger=None):
        self._log = logger or logging.getLogger(__name__)
```

Целевое состояние:
```python
from multiprocess_framework.modules.base_manager import BaseManager, ObservableMixin

class StateStoreManager(BaseManager, ObservableMixin, IStateStoreManager):
    def __init__(self, router=None, initial_state=None,
                 manager_name="StateStoreManager", logger=None, stats=None):
        BaseManager.__init__(self, manager_name=manager_name)
        ObservableMixin.__init__(self, managers={"logger": logger, "stats": stats})
        # убрать: self._log = logger or logging.getLogger(...)
        # заменить все self._log.* → self._log_*(...)
```

⚠️ Проверить MRO: `IStateStoreManager` может объявлять `initialize() -> None`, а `IBaseManager` — `initialize() -> bool`. Если есть конфликт — удалить дублирующий abstract method из `IStateStoreManager` и оставить только контракт `BaseManager`.

**Также:** передать `self._log_*` как callable в `DeltaDispatcher`, чтобы тот не создавал свой logger.

### 1.2 `StateProxy` (и `GuiStateProxy` по наследованию)

**Файл:** `modules/state_store_module/proxy/state_proxy.py`

```python
class StateProxy(BaseManager, ObservableMixin, IStateProxy):
    def __init__(self, process_name, router, server_target="ProcessManager",
                 manager_name=None, logger=None):
        BaseManager.__init__(self, manager_name=manager_name or f"StateProxy:{process_name}")
        ObservableMixin.__init__(self, managers={"logger": logger})
        # process_name остаётся как атрибут для IPC-адресации
```

`GuiStateProxy` наследует `StateProxy` — получает изменение автоматически.

### 1.3 `ChainThreadPool`

**Файл:** `modules/chain_module/thread_pool/pool.py`

```python
class ChainThreadPool(BaseManager, ObservableMixin):
    def __init__(self, max_workers=2, step_timeout=10.0, logger=None):
        BaseManager.__init__(self, manager_name="ChainThreadPool")
        ObservableMixin.__init__(self, managers={"logger": logger})
        # создание ThreadPoolExecutor остаётся в __init__ (не в initialize())
        # так как pool создаётся вместе с объектом, а не позже
    
    def initialize(self) -> bool:
        self.is_initialized = True
        return True
    
    def shutdown(self) -> bool:
        self._executor.shutdown(wait=True)
        self.is_initialized = False
        return True
```

### 1.4 `RegistersManager`

**Файл:** `modules/registers_module/core/manager.py`

```python
class RegistersManager(BaseManager, ObservableMixin):
    def __init__(self, registers=None, connection_map=None,
                 send_callback=None, logger=None, stats=None):
        BaseManager.__init__(self, manager_name="RegistersManager")
        ObservableMixin.__init__(self, managers={"logger": logger, "stats": stats})
    
    def initialize(self) -> bool:
        self.is_initialized = True
        return True
    
    def shutdown(self) -> bool:
        self._global_observers.clear()
        self._field_observers.clear()
        self.is_initialized = False
        return True
```

---

## Фаза 2 — Logger injection для не-менеджерских классов

Для этих классов полный BaseManager избыточен — они execution objects или утилиты. Паттерн: принять `logger: Any = None`, использовать его или fallback.

### 2.1 `ChainContext` — добавить поле logger

**Файл:** `modules/chain_module/core/context.py`

```python
@dataclass
class ChainContext:
    camera_id: str = ""
    region_id: str = ""
    seq_id: int = 0
    # ...
    logger: Any = None  # ObservableMixin или любой duck-typed объект с _log_*
```

`ChainRunnable`, `DagRunnable`, `ParallelChainRunnable` — вместо модульного logger использовать `context.logger` если задан:

```python
# Было:
logger.warning("Step %s failed: %s", step.node.node_id, e)

# Станет:
_log = context.logger if context and context.logger else logger
_log.warning(...)  # или _log._log_warning(...) если это ObservableMixin
```

⚠️ Duck-typing: context.logger может быть ObservableMixin (методы `_log_*`) или stdlib logger (методы `warning/info`). Решение: хелпер `_emit(log_obj, level, msg)` или принять что в context только `ObservableMixin`-совместимый объект.

Рекомендую: context.logger принимает объект с методами `_log_info`, `_log_warning`, `_log_error`. Если не задан — исполнители молчат (no-op).

### 2.2 `WorkerPoolDispatcher` — logger injection

**Файл:** `modules/chain_module/worker_pool/dispatcher.py`

```python
class WorkerPoolDispatcher:
    def __init__(self, send_fn, worker_count, timeout=5.0,
                 input_queue_size=16, logger=None):
        self._log = logger  # None → тихо; вызывающий передаёт ObservableMixin
```

### 2.3 `LatencyTracker` — убрать loguru

**Файл:** `modules/chain_module/metrics/latency.py`

```python
# Убрать: from loguru import logger
class LatencyTracker:
    def __init__(self, name, log_interval=100, logger=None):
        self._log = logger
```

### 2.4 `DeltaDispatcher` — logger injection

**Файл:** `modules/state_store_module/manager/delta_dispatcher.py`

```python
class DeltaDispatcher:
    def __init__(self, subscription_mgr, router, sender_name="StateStore", logger=None):
        self._log = logger
```

`StateStoreManager` передаёт свой `self` (ObservableMixin) как logger в DeltaDispatcher.

---

## Фаза 3 — Внутренние субкомпоненты (logger injection от родителя)

Эти файлы достаточно обновить, передав logger из родительского менеджера:

| Файл | Текущий паттерн | Действие |
|------|----------------|----------|
| `state_store_module/middleware/base.py` | `logging.getLogger` | принять `logger` в `StateMiddleware.__init__` |
| `state_store_module/middleware/logging_mw.py` | `logging.getLogger` | наследует от StateMiddleware |
| `state_store_module/middleware/validation.py` | `logging.getLogger` | аналогично |
| `shared_resources_module/buffers/registry.py` (`ShmRegistry`) | `logging.getLogger` | принять `logger` из `SharedResourcesManager` |
| `shared_resources_module/state/process_state_registry.py` | уже принимает `logger` | проверить, что `SharedResourcesManager` передаёт свой |
| `console_module/commands/register_commands.py` | `logging.getLogger` | принять `logger` из `ConsoleManager` |
| `process_manager_module/process/topology_manager.py` | `logging.getLogger` | принять `logger` из `ProcessManagerProcess` |

**Что НЕ трогать:**
- `logger_module/channels/log_channel.py` — это реализация самой системы логирования, использует stdlib как transport
- `data_schema_module/registry/` — leaf-модуль, не может зависеть от base_manager
- `frontend_module` виджеты — UI-компоненты, stdlib logging приемлем; слишком много файлов, отдельная задача

---

## Фаза 4 — ADR-SS-006: авто-регистрация `state.changed` в ProcessModule

**Файл:** `modules/process_module/core/process_module.py`

Добавить опциональный параметр `state_proxy`:

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from multiprocess_framework.modules.state_store_module.interfaces import IStateProxy

class ProcessModule(BaseManager, ObservableMixin, IProcessModule):
    def __init__(self, ..., state_proxy: "IStateProxy | None" = None):
        ...
        self._state_proxy = state_proxy
    
    def initialize(self) -> bool:
        result = super().initialize()
        if self._state_proxy is not None:
            self.router.register_message_handler(
                "state.changed",
                self._state_proxy.on_state_changed,
            )
        return result
```

⚠️ Импорт `IStateProxy` — через `TYPE_CHECKING` чтобы не создавать circular dependency на runtime. `state_store_module` → `IRouter` (Protocol), `process_module` → `IStateProxy` (TYPE_CHECKING only) — допустимо.

---

## Фаза 5 — Документация

### 5.1 PyQt5 → PySide6 (3 файла)

| Файл | Строки | Изменение |
|------|--------|-----------|
| `docs/MODULES_OVERVIEW.md` | 255, 259 | «PyQt5-виджеты» → «PySide6-виджеты», `PyQt5` → `PySide6` |
| `docs/MODULE_CONTRACTS.md` | 469, 484, 486 | аналогично |
| `modules/frontend_module/docs/IDEAS_AND_IMPROVEMENTS.md` | 57 | обновить описание текущего состояния |

`DECISIONS.md` — **не трогать**: строки 705 и 1604 — это исторические ADR (описывают прошлое решение «требовал PyQt5»). Исправлять историю ADR не принято.

### 5.2 MODULE_CONTRACTS.md — добавить 2 модуля

**Файл:** `docs/MODULE_CONTRACTS.md`

Добавить секции (по стандартному формату из документа) для:

**`chain_module` (L6):**
- Цель: DAG/Chain execution engine для pipeline-операций
- Контракт: `IChainRunnable`, `ChainRunnable`, `DagRunnable`, `ParallelChainRunnable`, `ChainContext`, `ChainResult`, `WorkerPoolDispatcher`, `ChainThreadPool`, graph utilities
- Инварианты: execution objects не являются менеджерами; logger передаётся через ChainContext; граница фреймворк/прототип — builder.py остаётся в прототипе
- Зависимости: `base_manager` (ChainThreadPool). Внешние: numpy
- Тестов: ~60+

**`state_store_module` (L5):**
- Цель: реактивное иерархическое дерево состояния с server/client разделением
- Контракт: `IRouter`, `IStateStore`, `IStateProxy`, `IStateStoreManager`, `StateStoreManager`, `StateProxy`, `GuiStateProxy`, `TreeStore`, `Delta`, middleware, selectors, `InMemoryRouter`
- Инварианты: IRouter — Protocol (не конкретный RouterManager); server в ProcessManager, client в каждом рабочем процессе; delta-only доставка
- Зависимости: `base_manager`. Внешние: опционально PySide6
- Тестов: ~415+

### 5.3 chain_module STATUS.md — обновить

**Файл:** `modules/chain_module/STATUS.md`

Раздел «Тесты»: заменить «заглушка, тесты планируются в Phase 3» на фактический статус — тесты написаны (`test_chain_runnable.py`, `test_dag_runnable.py`, `test_latency_tracker.py`, `test_thread_pool.py`, `test_topology.py`).

---

## Порядок реализации

```
1. Фаза 5.1–5.3  (документация — нет рисков, изолировано)
2. Фаза 1.4      (RegistersManager — проще всего, нет внешних зависимостей)
3. Фаза 1.3      (ChainThreadPool)
4. Фаза 2.2–2.4  (WorkerPoolDispatcher, LatencyTracker, DeltaDispatcher)
5. Фаза 2.1      (ChainContext.logger + executors)
6. Фаза 1.1      (StateStoreManager — самый сложный MRO)
7. Фаза 1.2      (StateProxy / GuiStateProxy)
8. Фаза 3        (субкомпоненты — передача logger от родителей)
9. Фаза 4        (ProcessModule ADR-SS-006)
```

---

## Критические файлы

| Файл | Фаза |
|------|------|
| `modules/state_store_module/manager/state_store_manager.py` | 1.1 |
| `modules/state_store_module/proxy/state_proxy.py` | 1.2 |
| `modules/state_store_module/manager/delta_dispatcher.py` | 2.4 |
| `modules/state_store_module/middleware/base.py` | 3 |
| `modules/state_store_module/interfaces.py` | 1.1 (MRO проверка) |
| `modules/chain_module/thread_pool/pool.py` | 1.3 |
| `modules/chain_module/worker_pool/dispatcher.py` | 2.2 |
| `modules/chain_module/metrics/latency.py` | 2.3 |
| `modules/chain_module/core/context.py` | 2.1 |
| `modules/chain_module/core/chain.py` | 2.1 |
| `modules/chain_module/core/dag.py` | 2.1 |
| `modules/chain_module/core/parallel.py` | 2.1 |
| `modules/registers_module/core/manager.py` | 1.4 |
| `modules/process_module/core/process_module.py` | 4 |
| `docs/MODULE_CONTRACTS.md` | 5.2 |
| `docs/MODULES_OVERVIEW.md` | 5.1 |

---

## Верификация

```bash
# Из корня проекта:
python scripts/run_framework_tests.py

# Специфично для изменённых модулей:
cd multiprocess_framework
python -m pytest modules/chain_module/tests/ -v
python -m pytest modules/state_store_module/tests/ -v
python -m pytest modules/registers_module/ -v

# Проверить что imports работают:
python -c "from multiprocess_framework.modules.state_store_module import StateStoreManager, StateProxy"
python -c "from multiprocess_framework.modules.chain_module import ChainRunnable, WorkerPoolDispatcher, ChainThreadPool"
python -c "from multiprocess_framework import RegistersManager"
```

Ожидаемый результат: все существующие тесты проходят (≥1877 passed), новые import-проверки без ошибок.
