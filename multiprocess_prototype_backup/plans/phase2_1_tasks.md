# План: Фаза 2.1 — Перенос state_store во фреймворк

**Дата:** 2026-04-30
**Статус:** DRAFT
**Фаза 0:** DONE (9 коммитов)
**Фаза 1:** DONE (6 коммитов, 40 unit + 14 integration тестов)

---

## Раздел 1: Разведка — что выяснено

### 1.1 Структура state_store — 9 поддиректорий

| Поддиректория | Файлы | Внешние зависимости | Внутренние зависимости |
|---|---|---|---|
| `core/` | delta.py, tree_store.py, subscription_manager.py | stdlib only | delta ← tree_store, delta ← subscription_manager |
| `manager/` | state_store_manager.py, delta_dispatcher.py | `core/`, `middleware/base` | delta_dispatcher ← core; ssm ← core + middleware |
| `proxy/` | state_proxy.py, gui_state_proxy.py | `core/delta`, PySide6 (lazy) | gui_proxy ← state_proxy |
| `middleware/` | base.py, throttle.py, validation.py, logging_mw.py, metrics.py | `core/delta`, `core/subscription_manager` | все ← base |
| `selectors/` | selector.py | `core/delta`, `core/subscription_manager`, `core/tree_store` | нет |
| `devtools/` | inspector.py | `core/delta`, `core/tree_store`, `core/subscription_manager`, `middleware/metrics` (TYPE_CHECKING) | нет |
| `health/` | monitor.py | `core/tree_store`, `core/subscription_manager._match_pattern`, `core/subscription_manager._split_pattern` | нет |
| `persistence/` | persistence_manager.py | `core/delta`, `core/tree_store`, `middleware/base`, yaml | нет |
| `recipes/` | recipe_engine.py, migrations/v1_to_v2.py | `core/tree_store`, `recipes/migrations` | recipe_engine ← migrations |

**Критическая находка по health/:** `monitor.py` импортирует приватные функции `_match_pattern` и `_split_pattern` из `core/subscription_manager.py`. При переносе нужно либо экспортировать их публично, либо инкапсулировать логику.

**Зависимость migration:** `v1_to_v2.py` является доменной (знает про "processing_blocks" и "nodes" бутылочного домена). Он используется только из `recipe_engine.py`. Это ЕДИНСТВЕННЫЙ доменный файл в `recipes/` — всё остальное generic.

### 1.2 Хардкод имён процессов

**Файл:** `state_store/proxy/state_proxy.py`, строка 27:
```python
_PROCESS_MANAGER = "ProcessManager"
```
Используется в 5 методах: `set()`, `merge()`, `get()`, `get_subtree()`, `subscribe()`, `unsubscribe()`, `shutdown()`. При переносе во фреймворк это нарушение: фреймворк не должен знать про имя процесса конкретного приложения.

### 1.3 Зависимости от RouterManager

`StateProxy._send()` вызывает `self._router.send_async(msg, priority="normal")` — нестандартная сигнатура для send_async (нет в типичных роутерах без priority). `_send_sync()` вызывает `self._router.send(msg)`. `StateStoreManager.register_message_handlers()` вызывает `router.register_message_handler(key, handler, expects_full_message=True)`. `DeltaDispatcher._send_state_changed()` вызывает `self._router.send_async(message, priority="normal")`.

Итого нужно формализовать `IRouter` с тремя методами:
- `register_message_handler(key: str, handler: Callable, expects_full_message: bool = True) -> None`
- `send_async(message: dict, priority: str = "normal") -> None`
- `send(message: dict) -> dict | None`

### 1.4 Все импортёры state_store в прототипе

Выявлено при чтении кода (grep по `from multiprocess_prototype.state_store`):

| Файл | Что импортирует |
|---|---|
| `backend/processes/camera/process.py:63` | `StateProxy` (lazy import) |
| `backend/processes/process_manager/process.py:59-68` | `StateStoreManager`, `build_initial_state`, `ValidationMiddleware`, `ThrottleMiddleware` (lazy) |
| `frontend/launcher.py:27` | `CameraStateAdapter` (останется в прототипе) |
| `frontend/launcher.py:113` | `RegistersStateAdapter` (lazy, останется в прототипе) |
| `state_store/adapters/registers_adapter.py:19` | `Delta` |
| `state_store/adapters/camera_state_adapter.py` | `GuiStateProxy`, `Delta` (косвенно) |
| `state_store/adapters/recipe_adapter.py` | `RecipeEngine` |
| `tests/integration/test_state_store_integration.py` | `build_initial_state`, `Delta`, `StateStoreManager`, `StateProxy` |
| `tests/unit/test_process_manager_app.py` | (косвенно через ProcessManagerProcessApp) |
| `state_store/tests/*.py` | все тесты внутри state_store |

**Прямые импортёры снаружи state_store/ (требуют обновления после переноса):**
1. `backend/processes/camera/process.py` — 1 lazy import
2. `backend/processes/process_manager/process.py` — 4 lazy imports
3. `tests/integration/test_state_store_integration.py` — 4 imports
4. `frontend/launcher.py` — 2 imports (adapters, остаются в прототипе)

Итого **~10 import-statements в 3 файлах-источниках** (не считая адаптеры, которые останутся в прототипе). Это умеренный риск, не критический.

### 1.5 Тесты state_store — инвентаризация

Файлы в `state_store/tests/`:
- `test_delta.py` — тесты Delta, MISSING, Transaction (generic → fw)
- `test_tree_store.py` — тесты TreeStore (generic → fw)
- `test_subscription_manager.py` — 25+ тестов (generic → fw)
- `test_state_store_manager.py` — StateStoreManager + DeltaDispatcher + MockRouter (generic → fw)
- `test_middleware.py` — pipeline, ValidationMiddleware, ThrottleMiddleware (generic → fw)
- `test_inspector.py` — StateInspector (generic → fw)
- `test_persistence.py` — PersistenceManager (generic → fw)
- `test_recipe_engine.py` — RecipeEngine (generic → fw, migration test НА ГРАНИЦЕ)

Файлы в прототипе, связанные с state_store:
- `tests/integration/test_state_store_integration.py` — 14 тестов end-to-end (остаются в прототипе, меняют импорты)
- `tests/unit/test_state_store_config.py` — unit тесты доменных правил (остаются)
- `tests/unit/test_process_manager_app.py` — unit тесты ProcessManagerProcessApp (остаются)

**Что переезжает в fw:** все файлы `state_store/tests/` кроме recipe_engine-тестов migration-части.
**Что остаётся:** тесты integration + unit в `tests/` прототипа (только меняют импорты).

### 1.6 Доменный код migration (граничный случай)

`recipes/migrations/v1_to_v2.py` содержит доменную логику (знает про "processing_blocks", "nodes" — специфика бутылочного pipeline-редактора). Он используется только из `recipe_engine.py` через `from .migrations import ...`.

**Решение:** `recipe_engine.py` переезжает в fw, но зависимость от migration реализуется через Protocol/callback. RecipeEngine принимает опциональный `migration_fn: Callable | None = None`, вызывает его если задан. В прототипе при создании RecipeEngine передаётся `migration_fn=migrate_recipe_data` из локального `recipes/migrations/v1_to_v2.py`. Это исключает доменный код из фреймворка.

### 1.7 Зависимости между поддиректориями (граф для стратегии B)

```
core/        — нет внешних зависимостей (stdlib only)
    ↑
middleware/  — зависит от core/delta, core/subscription_manager
    ↑
manager/     — зависит от core/, middleware/base
    ↑
proxy/       — зависит от core/delta (+ PySide6 lazy)
devtools/    — зависит от core/, middleware/metrics (TYPE_CHECKING)
health/      — зависит от core/ (tree_store + _match_pattern/_split_pattern)
persistence/ — зависит от core/, middleware/base
selectors/   — зависит от core/
recipes/     — зависит от core/tree_store (+ migration_fn через параметр)
```

Граф DAG, циклов нет.

---

## Раздел 2: Стратегия миграции

### Выбранная стратегия: C — Compat-обёртки в прототипе

**Обоснование:** Стратегия C даёт возможность в одной большой подзадаче (2.1.2) скопировать весь код в fw, и сразу проверить тесты ОБОИХ мест: новый `fw/modules/state_store_module/tests/` и старые `state_store/tests/` через shim-ы. Shim-файлы — это просто `from multiprocess_framework.modules.state_store_module.X import *`, ни строки реализации. После верификации — одна подзадача (2.1.4) зачищает shim-ы и удаляет дублирование.

Стратегия A слишком рискованна — большой атомарный шаг, сложно откатывать. Стратегия B требует 9 коммитов-шагов и сложной оркестрации shim-ов на каждом шаге. Стратегия C даёт лучший баланс: можно запустить тесты сразу после 2.1.2 (шаг "copy"), убедиться что всё работает, затем спокойно мигрировать импорты.

**Этапы стратегии C:**
1. Архитектурные решения + интерфейсы (2.1.1)
2. Копирование generic-кода + адаптация migration_fn (2.1.2)
3. Shim-ы в прототипе + верификация тестов (2.1.3)
4. Замена реальных импортов + удаление shim-ов (2.1.4)
5. Документация модуля (2.1.5)

---

## Раздел 3: Архитектурные решения

### ADR-SS-001: IRouter Protocol

**Проблема:** `StateProxy` и `DeltaDispatcher` зависят от `RouterManager` через утиный тип. При переносе во фреймворк нельзя импортировать RouterManager напрямую — круговая зависимость.

**Решение:** В `interfaces.py` нового модуля определить `Protocol`:

```python
class IRouter(Protocol):
    def register_message_handler(
        self, key: str, handler: Callable, expects_full_message: bool = True
    ) -> None: ...

    def send_async(self, message: dict, priority: str = "normal") -> None: ...

    def send(self, message: dict) -> dict | None: ...
```

Аннотации в `StateProxy.__init__`, `StateStoreManager.__init__`, `DeltaDispatcher.__init__` меняются с `router: Any` на `router: IRouter | None`. RouterManager прототипа/фреймворка уже реализует этот контракт — изменений в RouterManager не требуется.

**Последствие:** При тестах MockRouter/MockBus тоже нужно реализовывать метод `send(msg)` для синхронного вызова. Это уже есть в `MockBus` интеграционного теста.

### ADR-SS-002: Конфигурируемый server_target в StateProxy

**Проблема:** `_PROCESS_MANAGER = "ProcessManager"` — модульный хардкод. После переноса во фреймворк фреймворк будет знать имя процесса конкретного приложения. Нарушение принципа "фреймворк не знает о прикладном слое".

**Решение:** Убрать модульную константу. Добавить параметр в конструктор:

```python
def __init__(
    self,
    process_name: str,
    router: IRouter | None = None,
    server_target: str = "ProcessManager",  # default для обратной совместимости
) -> None:
```

Все 5 методов, использующих `_PROCESS_MANAGER`, заменяют его на `self._server_target`.

**Места обновления в прототипе:**
- `backend/processes/camera/process.py:65` — передать `server_target="ProcessManager"` явно (ясность намерений)
- `frontend/launcher.py` — при создании `GuiStateProxy` для GUI-процесса передать явно
- `state_store/devtools/inspector.py` — не использует, не трогать
- Тесты integration — `StateProxy("camera_0", ...)` — добавить `server_target="ProcessManager"` явно

**Важно:** Оставить `default="ProcessManager"` для плавной миграции. В Фазе 4 (лончер) убрать default → `server_target: str` без default. Сейчас задача Фазы 2.1 — добавить параметр с default (не ломая ничего), и задокументировать это как TODO.

### ADR-SS-003: Migration callback в RecipeEngine

**Проблема:** `recipe_engine.py` импортирует `from .migrations import migrate_recipe_data, needs_migration, RECIPE_VERSION_V2` — доменная зависимость.

**Решение:** RecipeEngine принимает опциональный `migration_fn`:

```python
def __init__(
    self,
    store: TreeStore,
    data_path: Path | str,
    migration_fn: Callable[[dict], dict] | None = None,
    migration_check_fn: Callable[[dict], bool] | None = None,
) -> None:
```

В `load()`: если `self._migration_check_fn is not None` и `self._migration_check_fn(data)` — вызвать `self._migration_fn(data)`.

В прототипе `adapters/recipe_adapter.py` при создании RecipeEngine передавать `migration_fn=migrate_recipe_data, migration_check_fn=needs_migration`.

**`migrations/` в fw:** создать `recipes/migrations/` с пустым `__init__.py` и `README.md` — место для generic миграций (если появятся). Доменный `v1_to_v2.py` остаётся в прототипе `state_store/recipes/migrations/v1_to_v2.py`.

### ADR-SS-004: Публичные хелперы _match_pattern и _split_pattern

**Проблема:** `health/monitor.py` импортирует приватные функции `_match_pattern` и `_split_pattern` из `core/subscription_manager.py`.

**Решение:** В `core/subscription_manager.py` — оставить их с именами `_match_pattern`/`_split_pattern`, но дополнительно экспортировать через `core/__init__.py` как публичные алиасы `match_pattern` и `split_pattern` (без underscore). В `health/monitor.py` изменить импорт на `from ...core import match_pattern, split_pattern`. В `middleware/throttle.py`, `middleware/validation.py`, `middleware/logging_mw.py` — аналогично, они тоже импортируют эти функции.

### ADR-SS-005: GuiStateProxy без top-level PySide6 import

`gui_state_proxy.py` уже импортирует PySide6 только внутри методов (lazy). Это правильно. При переносе — сохранить этот подход без изменений. PySide6 является опциональной зависимостью фреймворка (уже есть в `frontend_module`).

### ADR-SS-006: Авто-регистрация handler-а state.changed (TODO, не Фаза 2.1)

Текущий подход: каждый процесс явно вызывает `router.register_message_handler("state.changed", proxy.on_state_changed)`. Зафиксировать как TODO в `state_store_module/DECISIONS.md` для Фазы 4. Не делать сейчас — это затронет `ProcessModule` (базовый класс фреймворка).

### ADR-SS-007: exclude_self через DeltaDispatcher (TODO, не Фаза 2.1)

Сейчас `exclude_sources` отправляется в `state.subscribe` и хранится в `Subscription`. DeltaDispatcher в `match()` учитывает `exclude_sources`. Это правильная серверная логика. Никаких изменений не требуется.

### ADR-SS-008: Broadcast vs targets routing

DeltaDispatcher уже строит сообщение с `"targets": [subscriber]` — то есть адресная доставка, не broadcast. RouterManager получает это и роутит точечно. Ничего менять не нужно.

### ADR-SS-009: ABC для собственных публичных классов, Protocol для внешних зависимостей

**Проблема:** Текущий `interfaces.py` содержит только `IRouter` Protocol (контракт внешней зависимости). У собственных публичных классов (`TreeStore`, `StateProxy`, `StateStoreManager`) нет явного контракта — это нарушает принцип «модуль как часть конструктора фреймворка». Эталон `process_manager_module` имеет 3 ABC: `ISystemLauncher`, `IProcessManagerProcess`, `IProcessRegistry` — для собственных классов.

**Решение:** Два типа контрактов в `interfaces.py`:
- **Внешние зависимости** → `Protocol` + `@runtime_checkable` (утиная типизация, RouterManager уже реализует без изменений)
- **Собственные публичные классы** → `ABC` с `@abstractmethod` (явный контракт, mock-friendly, как в эталоне)

Добавить в `interfaces.py`:
- `IStateStore(ABC)` — контракт `TreeStore` (серверное дерево состояния)
- `IStateProxy(ABC)` — контракт `StateProxy` (клиентский прокси)
- `IStateStoreManager(ABC)` — контракт `StateStoreManager` (серверный фасад)

Соответствующие классы наследуют свой контракт:
- `TreeStore(IStateStore)` — задача 2.1.1
- `StateProxy(IStateProxy)` — задача 2.1.3
- `GuiStateProxy(IStateProxy)` — задача 2.1.3 (через цепочку от StateProxy)
- `StateStoreManager(IStateStoreManager)` — задача 2.1.3

**Последствие:** Добавление ABC-базового класса не требует изменений в реализации — только добавить наследование. Все существующие методы остаются без изменений. Даёт: mock-friendly тесты, явный публичный API, единообразие с другими модулями фреймворка.

### ADR-SS-010: testing/ подпакет — InMemoryRouter для прикладных тестов

**Проблема:** `MockBus` определён внутри `tests/integration/test_state_store_integration.py` (~50 строк). Любой прикладной код, использующий `StateProxy`, вынужден копировать этот mock при написании unit-тестов.

**Решение:** Вынести mock-реализацию в `state_store_module/testing/in_memory_router.py` как `InMemoryRouter`. Это часть **публичного API модуля** — экспортируется из главного `__init__.py`. Реализует `IRouter` Protocol (явное объявление `class InMemoryRouter(IRouter)` для статической проверки).

**Прецедент:** pytest-плагины, `unittest.mock`, `django.test` — все фреймворки традиционно предоставляют testing-helpers как часть публичного API.

**Объём:** `testing/in_memory_router.py` — ~50 строк (перенос из integration-теста). `testing/README.md` — пример использования.

---

## Раздел 4: Структура нового модуля

```
multiprocess_framework/modules/state_store_module/
│
├── __init__.py                    # Публичный API: экспорт всех ключевых классов (включая InMemoryRouter)
├── interfaces.py                  # IRouter (Protocol) + IStateStore, IStateProxy, IStateStoreManager (ABC)
├── README.md                      # Обзор модуля (русский)
├── STATUS.md                      # Статус (русский)
├── DECISIONS.md                   # ADR-SS-001...SS-010
│
├── core/
│   ├── __init__.py                # TreeStore, Delta, Transaction, MISSING, SubscriptionManager, Subscription
│   │                              # + публичные алиасы match_pattern, split_pattern
│   ├── delta.py                   # Delta, MISSING, Transaction (без изменений)
│   ├── tree_store.py              # TreeStore (без изменений)
│   └── subscription_manager.py   # SubscriptionManager + экспорт match_pattern, split_pattern
│
├── manager/
│   ├── __init__.py                # StateStoreManager, DeltaDispatcher
│   ├── state_store_manager.py     # router: IRouter | None
│   └── delta_dispatcher.py       # router: IRouter | None
│
├── proxy/
│   ├── __init__.py                # StateProxy, GuiStateProxy
│   ├── state_proxy.py             # + server_target: str = "ProcessManager"; router: IRouter | None
│   └── gui_state_proxy.py        # без изменений (lazy PySide6)
│
├── middleware/
│   ├── __init__.py                # StateMiddleware, MiddlewarePipeline, все конкретные
│   ├── base.py                    # без изменений
│   ├── throttle.py                # импорт _match_pattern/_split_pattern → match_pattern/split_pattern
│   ├── validation.py              # аналогично
│   ├── logging_mw.py              # аналогично
│   └── metrics.py                 # без изменений
│
├── selectors/
│   ├── __init__.py                # Selector, SelectorRegistry
│   └── selector.py                # без изменений
│
├── devtools/
│   ├── __init__.py                # StateInspector
│   └── inspector.py              # без изменений
│
├── health/
│   ├── __init__.py                # HealthMonitor, WatchedProcess
│   └── monitor.py                 # импорт → match_pattern/split_pattern (публичные)
│
├── persistence/
│   ├── __init__.py                # PersistenceManager
│   └── persistence_manager.py    # без изменений
│
├── recipes/
│   ├── __init__.py                # RecipeEngine
│   ├── recipe_engine.py           # + migration_fn/migration_check_fn параметры; убрать импорт migrations
│   └── migrations/
│       ├── __init__.py            # Пустой (место для generic миграций)
│       └── README.md              # Пояснение: доменные миграции — в прикладном слое
│
└── testing/
    ├── __init__.py                # InMemoryRouter (публичный API модуля)
    ├── in_memory_router.py        # Реализация (~50 строк, перенесена из integration-теста)
    └── README.md                  # Как использовать в прикладных тестах
```

**В прототипе остаётся:**
```
multiprocess_prototype/state_store/
├── __init__.py                    # → shim: переэкспорт из fw (Задача 2.1.3), потом удаляется (2.1.4)
├── bootstrap.py                   # ОСТАЁТСЯ (доменный код)
├── adapters/
│   ├── camera_state_adapter.py    # ОСТАЁТСЯ
│   ├── recipe_adapter.py          # ОСТАЁТСЯ (+ передаёт migration_fn в RecipeEngine)
│   └── registers_adapter.py      # ОСТАЁТСЯ
└── recipes/
    └── migrations/
        └── v1_to_v2.py            # ОСТАЁТСЯ (доменный)
```

---

## Раздел 5: Подзадачи

### Задача 2.1.0 — Подготовка: создание скелета модуля и interfaces.py

**Уровень:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** создать пустую структуру директорий `multiprocess_framework/modules/state_store_module/` с полностью заполненным `interfaces.py` (IRouter Protocol + IStateStore, IStateProxy, IStateStoreManager ABC) и пустыми `__init__.py` во всех поддиректориях.
**Context:** Без этой задачи следующие задачи не могут работать параллельно. Интерфейсы должны быть зафиксированы до начала переноса кода. По ADR-SS-009: собственные публичные классы получают ABC, внешние зависимости — Protocol. Это единообразно с эталоном `process_manager_module` (3 ABC: ISystemLauncher, IProcessManagerProcess, IProcessRegistry).

**Файлы (создать):**
- `multiprocess_framework/modules/state_store_module/__init__.py` — пустой
- `multiprocess_framework/modules/state_store_module/interfaces.py` — IRouter Protocol + IStateStore/IStateProxy/IStateStoreManager ABC
- `multiprocess_framework/modules/state_store_module/core/__init__.py` — пустой
- `multiprocess_framework/modules/state_store_module/manager/__init__.py` — пустой
- `multiprocess_framework/modules/state_store_module/proxy/__init__.py` — пустой
- `multiprocess_framework/modules/state_store_module/middleware/__init__.py` — пустой
- `multiprocess_framework/modules/state_store_module/selectors/__init__.py` — пустой
- `multiprocess_framework/modules/state_store_module/devtools/__init__.py` — пустой
- `multiprocess_framework/modules/state_store_module/health/__init__.py` — пустой
- `multiprocess_framework/modules/state_store_module/persistence/__init__.py` — пустой
- `multiprocess_framework/modules/state_store_module/recipes/__init__.py` — пустой
- `multiprocess_framework/modules/state_store_module/recipes/migrations/__init__.py` — пустой
- `multiprocess_framework/modules/state_store_module/tests/__init__.py` — пустой

**Содержание interfaces.py:**

```python
"""interfaces.py — Публичные контракты state_store_module.

Контракты двух типов (ADR-SS-009):
    IRouter (Protocol)          — внешняя зависимость, утиная типизация
    IStateStore (ABC)           — контракт TreeStore (серверное дерево состояния)
    IStateProxy (ABC)           — контракт StateProxy (клиентский прокси)
    IStateStoreManager (ABC)    — контракт StateStoreManager (серверный фасад)

Внешние модули импортируют только из interfaces.py, не из внутренних подпакетов.
"""
from abc import ABC, abstractmethod
from typing import Any, Callable, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Внешняя зависимость — Protocol (утиная типизация, ADR-SS-001)
# RouterManager уже реализует этот контракт без изменений.
# ---------------------------------------------------------------------------

@runtime_checkable
class IRouter(Protocol):
    """Минимальный контракт Router для state_store_module.

    Не импортировать RouterManager напрямую — только через этот Protocol.
    """
    def register_message_handler(
        self,
        key: str,
        handler: Callable,
        expects_full_message: bool = True,
    ) -> None: ...

    def send_async(self, message: dict, priority: str = "normal") -> None: ...

    def send(self, message: dict) -> dict | None: ...


# ---------------------------------------------------------------------------
# Собственные публичные классы — ABC (ADR-SS-009)
# Точные сигнатуры берутся из существующих реализаций:
#   tree_store.py, state_proxy.py, state_store_manager.py
# Включать только публичные методы (без _).
# ---------------------------------------------------------------------------

class IStateStore(ABC):
    """Контракт TreeStore — серверное дерево состояния.

    TreeStore наследует IStateStore в задаче 2.1.1.
    """

    @abstractmethod
    def get(self, path: str, default: Any = None) -> Any:
        """Получить значение по пути."""
        ...

    @abstractmethod
    def get_subtree(self, path: str) -> dict:
        """Получить поддерево по пути."""
        ...

    @abstractmethod
    def set(self, path: str, value: Any, source: str = "system") -> "Delta | None":
        """Установить значение. Возвращает Delta или None если значение не изменилось."""
        ...

    @abstractmethod
    def merge(self, path: str, partial: dict, source: str = "system") -> "Delta | None":
        """Смержить partial dict по пути."""
        ...

    @abstractmethod
    def delete(self, path: str, source: str = "system") -> "Delta | None":
        """Удалить узел по пути."""
        ...

    @abstractmethod
    def subscribe(self, pattern: str, callback: Callable) -> str:
        """Подписаться на изменения по паттерну. Возвращает subscription_id."""
        ...

    @abstractmethod
    def unsubscribe(self, subscription_id: str) -> None:
        """Отписаться по subscription_id."""
        ...


class IStateProxy(ABC):
    """Контракт StateProxy — клиентский прокси (живёт в каждом процессе).

    StateProxy наследует IStateProxy в задаче 2.1.3.
    GuiStateProxy наследует через цепочку от StateProxy.
    """

    @abstractmethod
    def get(self, path: str, default: Any = None) -> Any:
        """Получить значение из локального кэша."""
        ...

    @abstractmethod
    def set(self, path: str, value: Any) -> None:
        """Отправить state.set на сервер."""
        ...

    @abstractmethod
    def merge(self, path: str, partial: dict) -> None:
        """Отправить state.merge на сервер."""
        ...

    @abstractmethod
    def subscribe(
        self,
        pattern: str,
        callback: Callable,
        exclude_self: bool = False,
    ) -> str:
        """Подписаться на изменения. Возвращает subscription_id."""
        ...

    @abstractmethod
    def unsubscribe(self, sub_id: str) -> None:
        """Отписаться по subscription_id."""
        ...

    @abstractmethod
    def on_state_changed(self, message: dict) -> None:
        """Handler для входящего state.changed сообщения от сервера."""
        ...


class IStateStoreManager(ABC):
    """Контракт StateStoreManager — серверный фасад (живёт в ProcessManager).

    StateStoreManager наследует IStateStoreManager в задаче 2.1.3.
    """

    @abstractmethod
    def initialize(self) -> bool:
        """Инициализировать хранилище. Возвращает True при успехе."""
        ...

    @abstractmethod
    def shutdown(self) -> None:
        """Graceful остановка."""
        ...

    @abstractmethod
    def use(self, middleware: "StateMiddleware") -> "IStateStoreManager":
        """Подключить middleware. Возвращает self для цепочки вызовов."""
        ...

    @abstractmethod
    def register_commands(self, command_manager: Any) -> None:
        """Зарегистрировать команды управления в CommandManager."""
        ...

    @abstractmethod
    def register_message_handlers(self, router: IRouter) -> None:
        """Зарегистрировать IPC message-handlers в Router."""
        ...
```

**Шаги:**
1. Создать все директории с `__init__.py`
2. Написать `interfaces.py` — `IRouter` Protocol (3 метода, ADR-SS-001) + `IStateStore`, `IStateProxy`, `IStateStoreManager` ABC (ADR-SS-009). Сигнатуры методов уточнить по существующим файлам `tree_store.py`, `state_proxy.py`, `state_store_manager.py` в прототипе — включать только публичные методы (без `_`)
3. Добавить `recipes/migrations/README.md` — пояснение что доменные миграции в прикладном слое
4. Проверить все 4 контракта

**Acceptance criteria:**
- [ ] `python -c "from multiprocess_framework.modules.state_store_module.interfaces import IRouter, IStateStore, IStateProxy, IStateStoreManager; print('OK')"` выводит OK
- [ ] Все директории созданы, все `__init__.py` существуют
- [ ] `IRouter` имеет ровно 3 метода с правильными сигнатурами
- [ ] `IStateStore`, `IStateProxy`, `IStateStoreManager` — ABC с `@abstractmethod`
- [ ] `isinstance(object(), IRouter)` не бросает — Protocol `@runtime_checkable`

**Out of scope:** реализация, копирование кода, добавление `testing/` (это Задача 2.1.0a)
**Edge cases:** forward-reference `"Delta | None"` в сигнатурах IStateStore — использовать строковую аннотацию или `TYPE_CHECKING` импорт
**Dependencies:** нет

---

---

### Задача 2.1.0a — testing/ подпакет: InMemoryRouter

**Уровень:** Junior (Haiku, normal)
**Assignee:** docs-writer
**Goal:** создать `state_store_module/testing/` с `InMemoryRouter` — переиспользуемый mock, вынесенный из integration-теста в публичный API модуля.
**Context:** По ADR-SS-010: `MockBus` (~50 строк) сейчас определён внутри `tests/integration/test_state_store_integration.py` и не переиспользуется. Любой прикладной модуль, интегрирующийся с StateProxy, вынужден копировать этот mock. `InMemoryRouter` становится частью публичного API — экспортируется из главного `__init__.py`.

**Файлы (создать):**
- `multiprocess_framework/modules/state_store_module/testing/__init__.py` — экспортирует `InMemoryRouter`
- `multiprocess_framework/modules/state_store_module/testing/in_memory_router.py` — реализация
- `multiprocess_framework/modules/state_store_module/testing/README.md` — пример использования

**Содержание in_memory_router.py** (перенос из `MockBus` + адаптация):

```python
"""in_memory_router.py — InMemoryRouter для unit-тестов прикладного кода.

Реализует IRouter Protocol без реальных IPC-каналов.
Сообщения доставляются синхронно в том же процессе.

Использование:
    from multiprocess_framework.modules.state_store_module.testing import InMemoryRouter

    router = InMemoryRouter()
    manager = StateStoreManager(initial_state={})
    manager.register_message_handlers(router)
    proxy = StateProxy("test_proc", router=router, server_target="test_manager")
    router.register_message_handler("state.changed", proxy.on_state_changed)
"""
from collections import defaultdict
from typing import Any, Callable


class InMemoryRouter:
    """Mock-реализация IRouter для тестирования.

    Хранит зарегистрированные handlers и доставляет сообщения синхронно.
    Совместим с IRouter Protocol (ADR-SS-001).
    """

    def __init__(self) -> None:
        self._handlers: dict[str, Callable] = {}
        self.sent_messages: list[dict] = []  # для assertions в тестах

    def register_message_handler(
        self,
        key: str,
        handler: Callable,
        expects_full_message: bool = True,
    ) -> None:
        self._handlers[key] = handler

    def send_async(self, message: dict, priority: str = "normal") -> None:
        """Синхронная доставка (в тестах async не нужен)."""
        self.sent_messages.append(message)
        key = message.get("type") or message.get("command")
        if key and key in self._handlers:
            self._handlers[key](message)

    def send(self, message: dict) -> dict | None:
        self.sent_messages.append(message)
        key = message.get("type") or message.get("command")
        if key and key in self._handlers:
            return self._handlers[key](message)
        return None

    def clear(self) -> None:
        """Сбросить историю сообщений между тестами."""
        self.sent_messages.clear()
```

**Шаги:**
1. Прочитать `multiprocess_prototype/tests/integration/test_state_store_integration.py` — найти класс `MockBus`, понять его интерфейс (какие методы, как используется в тестах)
2. Создать `testing/in_memory_router.py` — перенести логику `MockBus`, переименовать в `InMemoryRouter`, адаптировать сигнатуры под `IRouter` Protocol
3. Создать `testing/__init__.py`:
   ```python
   from .in_memory_router import InMemoryRouter
   __all__ = ["InMemoryRouter"]
   ```
4. Создать `testing/README.md` — примеры использования (минимум: как создать StateProxy с InMemoryRouter в тесте)
5. Проверить: `python -c "from multiprocess_framework.modules.state_store_module.testing import InMemoryRouter; r = InMemoryRouter(); print('OK')"`

**Acceptance criteria:**
- [ ] `python -c "from multiprocess_framework.modules.state_store_module.testing import InMemoryRouter; r = InMemoryRouter(); print('OK')"` выводит OK
- [ ] `InMemoryRouter` имеет методы `register_message_handler`, `send_async`, `send` (совместим с `IRouter`)
- [ ] `InMemoryRouter.sent_messages` — список для assertions
- [ ] `InMemoryRouter.clear()` — метод сброса истории
- [ ] `testing/README.md` содержит рабочий пример теста с StateProxy

**Out of scope:** перенос кода из integration-теста (удаление `MockBus` из теста — Задача 2.1.6), реализация StateProxy и StateStoreManager (это Задача 2.1.3)
**Edge cases:** `MockBus` в integration-тесте может иметь дополнительные методы специфичные для теста — брать только те, что относятся к `IRouter`
**Dependencies:** Задача 2.1.0

---

### Задача 2.1.1 — Перенос core/

**Уровень:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** скопировать `state_store/core/` в `state_store_module/core/` с обновлением импортов, публикацией `match_pattern`/`split_pattern` и добавлением `TreeStore(IStateStore)`.
**Context:** `core/` — основа всего модуля, без внешних зависимостей. По ADR-SS-009: `TreeStore` должен наследовать `IStateStore(ABC)` — это не меняет логику, только добавляет базовый класс.

**Файлы:**
- `multiprocess_prototype/state_store/core/delta.py` → копировать в `multiprocess_framework/modules/state_store_module/core/delta.py`
- `multiprocess_prototype/state_store/core/tree_store.py` → копировать в fw + добавить `(IStateStore)` в определение класса
- `multiprocess_prototype/state_store/core/subscription_manager.py` → копировать в fw + добавить публичные алиасы
- `multiprocess_framework/modules/state_store_module/core/__init__.py` — заполнить

**Шаги:**
1. Скопировать `delta.py` в fw. Обновить все `from multiprocess_prototype.state_store.core.delta import ...` → `from multiprocess_framework.modules.state_store_module.core.delta import ...` (внутри самого файла нет таких импортов, файл чистый).
2. Скопировать `tree_store.py` в fw. Обновить внутренний импорт: `from multiprocess_prototype.state_store.core.delta import Delta, MISSING, Transaction` → `from .delta import Delta, MISSING, Transaction`. Добавить импорт контракта и наследование:
   ```python
   from ..interfaces import IStateStore
   
   class TreeStore(IStateStore):  # было: class TreeStore:
       ...
   ```
   Убедиться что все методы, объявленные в `IStateStore` как `@abstractmethod`, реализованы в `TreeStore` (иначе класс не инстанциируется).
3. Скопировать `subscription_manager.py` в fw. Обновить внутренний импорт: `from multiprocess_prototype.state_store.core.delta import Delta` → `from .delta import Delta`. Добавить в конец файла публичные алиасы:
   ```python
   # Публичные алиасы для использования в health/, middleware/ — избегаем утечки приватных имён
   match_pattern = _match_pattern
   split_pattern = _split_pattern
   ```
4. Заполнить `core/__init__.py`: экспортировать `TreeStore`, `Delta`, `Transaction`, `MISSING`, `SubscriptionManager`, `Subscription`, `match_pattern`, `split_pattern`.
5. Добавить `tests/test_core.py` в fw (пустой файл с комментарием "тесты переедут в 2.1.6").

**Acceptance criteria:**
- [ ] `python -c "from multiprocess_framework.modules.state_store_module.core import TreeStore, Delta, SubscriptionManager, match_pattern; print('OK')"` — OK
- [ ] `python -c "from multiprocess_framework.modules.state_store_module.core import TreeStore; from multiprocess_framework.modules.state_store_module.interfaces import IStateStore; assert issubclass(TreeStore, IStateStore); print('TreeStore contract OK')"` — OK
- [ ] Никаких `from multiprocess_prototype` в fw-файлах core/
- [ ] `python scripts/validate.py` проходит без новых ошибок

**Out of scope:** обновление импортов в прототипе, перенос тестов
**Edge cases:** `_match_pattern`/`_split_pattern` должны оставаться в файле с underscore — алиасы только добавляются, не заменяются. `TreeStore` уже реализует все публичные методы — проверить соответствие сигнатурам в `IStateStore` (могут быть minor расхождения — приоритет у реализации, скорректировать `IStateStore` если нужно)
**Dependencies:** Задача 2.1.0

---

### Задача 2.1.2 — Перенос middleware/, selectors/, devtools/, health/, persistence/

**Уровень:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** скопировать 5 поддиректорий в fw с обновлением всех внутренних импортов на fw-пути.
**Context:** Эти блоки зависят только от `core/` (уже в fw). Логично перенести их за один шаг до переноса manager/ и proxy/ — они не зависят друг от друга.

**Файлы:**
- `middleware/base.py`, `middleware/throttle.py`, `middleware/validation.py`, `middleware/logging_mw.py`, `middleware/metrics.py` → fw/middleware/
- `selectors/selector.py` → fw/selectors/
- `devtools/inspector.py` → fw/devtools/
- `health/monitor.py` → fw/health/
- `persistence/persistence_manager.py` → fw/persistence/
- Соответствующие `__init__.py` — заполнить

**Шаги:**
1. Скопировать все файлы middleware/. В каждом файле заменить:
   - `from multiprocess_prototype.state_store.core.delta import Delta` → `from ..core.delta import Delta`
   - `from multiprocess_prototype.state_store.core.subscription_manager import _match_pattern, _split_pattern` → `from ..core import match_pattern, split_pattern` (публичные алиасы)
   - `from multiprocess_prototype.state_store.middleware.base import StateMiddleware` → `from .base import StateMiddleware`
2. Скопировать `selectors/selector.py`. Заменить все `from multiprocess_prototype.state_store.core.*` → `from ..core.*` и аналогично для subscription_manager (`_match_pattern`/`_split_pattern` → `match_pattern`/`split_pattern`).
3. Скопировать `devtools/inspector.py`. Заменить `from multiprocess_prototype.state_store.core.*` → `from ..core.*`. TYPE_CHECKING импорт MetricsMiddleware: `from ..middleware.metrics import MetricsMiddleware`.
4. Скопировать `health/monitor.py`. Заменить `from multiprocess_prototype.state_store.core.tree_store import TreeStore` → `from ..core.tree_store import TreeStore`. `from multiprocess_prototype.state_store.core.subscription_manager import _match_pattern, _split_pattern` → `from ..core import match_pattern, split_pattern`. В коде монитора — заменить вызовы `_match_pattern` → `match_pattern`, `_split_pattern` → `split_pattern`.
5. Скопировать `persistence/persistence_manager.py`. Заменить все `from multiprocess_prototype.state_store.core.*` → `from ..core.*` и `from multiprocess_prototype.state_store.middleware.base import StateMiddleware` → `from ..middleware.base import StateMiddleware`.
6. Заполнить все `__init__.py`.

**Acceptance criteria:**
- [ ] `python -c "from multiprocess_framework.modules.state_store_module.middleware import ValidationMiddleware, ThrottleMiddleware; print('OK')"` — OK
- [ ] `python -c "from multiprocess_framework.modules.state_store_module.health import HealthMonitor; print('OK')"` — OK
- [ ] `python -c "from multiprocess_framework.modules.state_store_module.persistence import PersistenceManager; print('OK')"` — OK
- [ ] `python -c "from multiprocess_framework.modules.state_store_module.devtools import StateInspector; print('OK')"` — OK
- [ ] `python -c "from multiprocess_framework.modules.state_store_module.selectors import Selector; print('OK')"` — OK
- [ ] Никаких `from multiprocess_prototype` во всех перенесённых файлах

**Out of scope:** тесты (Задача 2.1.5), manager/ и proxy/ (Задача 2.1.3)
**Edge cases:** `_match_pattern`/`_split_pattern` в health/monitor.py — заменить на публичные алиасы
**Dependencies:** Задача 2.1.1

---

### Задача 2.1.3 — Перенос manager/, proxy/, recipes/

**Уровень:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** скопировать оставшиеся поддиректории (manager/, proxy/, recipes/) в fw; решить ADR-SS-002 (server_target) и ADR-SS-003 (migration_fn); добавить наследование ABC-контрактов; заполнить главный `__init__.py` модуля.
**Context:** Это самая архитектурно-значимая задача Фазы 2.1: manager и proxy — центральные классы. Решение server_target меняет public API StateProxy. Решение migration_fn меняет API RecipeEngine. По ADR-SS-009: StateProxy, StateStoreManager должны наследовать свои ABC-контракты из interfaces.py.

**Файлы:**
- `manager/state_store_manager.py` → fw/manager/ (router: IRouter | None)
- `manager/delta_dispatcher.py` → fw/manager/ (router: IRouter | None)
- `proxy/state_proxy.py` → fw/proxy/ (+ server_target параметр; IRouter | None)
- `proxy/gui_state_proxy.py` → fw/proxy/ (без изменений по API)
- `recipes/recipe_engine.py` → fw/recipes/ (+ migration_fn/migration_check_fn параметры)
- `multiprocess_framework/modules/state_store_module/__init__.py` — заполнить публичный API

**Шаги:**
1. Скопировать `delta_dispatcher.py`. Заменить все `from multiprocess_prototype.*` → относительные. Тип router: `from ..interfaces import IRouter` → добавить аннотацию `router: IRouter | None = None`. Убрать `from typing import Any` если не используется далее (или оставить для обратной совместимости).

2. Скопировать `state_store_manager.py`. Аналогично обновить импорты. Добавить `from ..interfaces import IRouter, IStateStoreManager`. Тип `router: Any` → `router: IRouter | None`. Добавить наследование ABC-контракта: `class StateStoreManager(IStateStoreManager):` (было `class StateStoreManager:`). Убедиться что все методы, объявленные в `IStateStoreManager` как `@abstractmethod`, реализованы: `initialize`, `shutdown`, `use`, `register_commands`, `register_message_handlers`.

3. Скопировать `state_proxy.py`. Ключевые изменения:
   - Удалить модульную константу `_PROCESS_MANAGER = "ProcessManager"`
   - Добавить параметр конструктора: `server_target: str = "ProcessManager"` (default для backward compat)
   - Добавить `self._server_target = server_target`
   - Во всех 7 методах, где использовалась константа `_PROCESS_MANAGER`: заменить на `self._server_target`
   - Тип `router: Any` → `router: IRouter | None`
   - Добавить в начало файла: `from ..interfaces import IRouter, IStateProxy`
   - Добавить наследование ABC-контракта: `class StateProxy(IStateProxy):` (было `class StateProxy:`)
   - Убедиться что все методы, объявленные в `IStateProxy` как `@abstractmethod`, реализованы

4. Скопировать `gui_state_proxy.py`. Обновить относительный импорт `from .state_proxy import StateProxy`. Убедиться что PySide6 по-прежнему только lazy. Аннотация TYPE_CHECKING `from PySide6.QtCore import QObject` — оставить. `GuiStateProxy` наследует `StateProxy`, который наследует `IStateProxy` — цепочка уже правильная, дополнительных изменений не требуется.

5. Скопировать `recipe_engine.py`. Ключевые изменения:
   - Удалить `from .migrations import RECIPE_VERSION_V2, migrate_recipe_data, needs_migration`
   - Добавить параметры конструктора:
     ```python
     migration_fn: Callable[[dict], dict] | None = None,
     migration_check_fn: Callable[[dict], bool] | None = None,
     ```
   - Добавить `self._migration_fn = migration_fn` и `self._migration_check_fn = migration_check_fn`
   - В методе `load()`: заменить блок `if needs_migration(data): migrate_recipe_data(data)` на:
     ```python
     if self._migration_check_fn is not None and self._migration_check_fn(data):
         if self._migration_fn is not None:
             data = self._migration_fn(data)
     ```
   - Убрать константы `RECIPE_VERSION_V2` из файла, если они жёстко связаны с доменом. Если используются внутри engine — заменить на локальные значения (2).
   - Обновить все `from multiprocess_prototype.*` → относительные

6. Заполнить главный `__init__.py` модуля по образцу `process_manager_module/__init__.py` — с docstring-картой API, группировкой и явным `__all__`:
   ```python
   """state_store_module — реактивное дерево состояния для многопроцессных приложений.

   Публичный API:
       Контракты (interfaces.py):
           IRouter             — внешняя зависимость (Protocol, ADR-SS-001)
           IStateStore         — контракт TreeStore (ABC, ADR-SS-009)
           IStateProxy         — контракт StateProxy (ABC, ADR-SS-009)
           IStateStoreManager  — контракт StateStoreManager (ABC, ADR-SS-009)

       Реализации:
           StateStoreManager  — серверный фасад (manager/)
           StateProxy         — клиентский прокси (proxy/)
           GuiStateProxy      — клиентский прокси для PySide6 GUI (proxy/)

       Core:
           TreeStore, Delta, Transaction, MISSING,
           SubscriptionManager, Subscription,
           match_pattern, split_pattern  — публичные хелперы для middleware/health

       Middleware:
           StateMiddleware, MiddlewarePipeline,
           ThrottleMiddleware, ValidationMiddleware,
           LoggingMiddleware, MetricsMiddleware

       Остальное:
           Selector, SelectorRegistry   — selectors/
           StateInspector               — devtools/
           HealthMonitor, WatchedProcess — health/
           PersistenceManager           — persistence/
           RecipeEngine                 — recipes/
           DeltaDispatcher              — manager/

       Testing (ADR-SS-010):
           InMemoryRouter  — mock IRouter для unit-тестов прикладного кода
   """
   from .interfaces import IRouter, IStateStore, IStateProxy, IStateStoreManager
   from .core import (TreeStore, Delta, Transaction, MISSING,
                      SubscriptionManager, Subscription,
                      match_pattern, split_pattern)
   from .manager import StateStoreManager, DeltaDispatcher
   from .proxy import StateProxy, GuiStateProxy
   from .middleware import (StateMiddleware, MiddlewarePipeline,
                            ThrottleMiddleware, ValidationMiddleware,
                            LoggingMiddleware, MetricsMiddleware)
   from .selectors import Selector, SelectorRegistry
   from .devtools import StateInspector
   from .health import HealthMonitor, WatchedProcess
   from .persistence import PersistenceManager
   from .recipes import RecipeEngine
   from .testing import InMemoryRouter

   __all__ = [
       # Контракты
       "IRouter", "IStateStore", "IStateProxy", "IStateStoreManager",
       # Реализации
       "StateStoreManager", "StateProxy", "GuiStateProxy",
       # Core
       "TreeStore", "Delta", "Transaction", "MISSING",
       "SubscriptionManager", "Subscription",
       "match_pattern", "split_pattern",
       # Middleware
       "StateMiddleware", "MiddlewarePipeline",
       "ThrottleMiddleware", "ValidationMiddleware",
       "LoggingMiddleware", "MetricsMiddleware",
       # Selectors / DevTools / Health / Persistence / Recipes
       "Selector", "SelectorRegistry",
       "StateInspector",
       "HealthMonitor", "WatchedProcess",
       "PersistenceManager",
       "RecipeEngine",
       "DeltaDispatcher",
       # Testing
       "InMemoryRouter",
   ]
   ```

**Acceptance criteria:**
- [ ] `python -c "from multiprocess_framework.modules.state_store_module import StateStoreManager, StateProxy, RecipeEngine, IRouter, IStateStore, IStateProxy, IStateStoreManager, InMemoryRouter; print('OK')"` — OK
- [ ] `StateProxy("camera_0", server_target="ProcessManager")` создаётся без ошибок
- [ ] `StateProxy("camera_0")` (без server_target) создаётся без ошибок (default работает)
- [ ] `RecipeEngine(store, path)` (без migration_fn) создаётся без ошибок
- [ ] Контракты реализованы — проверка командой:
  ```python
  from multiprocess_framework.modules.state_store_module import (
      IStateStore, IStateProxy, IStateStoreManager,
      TreeStore, StateProxy, StateStoreManager
  )
  assert issubclass(TreeStore, IStateStore), 'TreeStore не реализует IStateStore'
  assert issubclass(StateProxy, IStateProxy), 'StateProxy не реализует IStateProxy'
  assert issubclass(StateStoreManager, IStateStoreManager), 'StateStoreManager не реализует IStateStoreManager'
  print('Все контракты реализованы')
  ```
- [ ] Никаких `from multiprocess_prototype` во всех fw-файлах
- [ ] `python scripts/validate.py` проходит

**Out of scope:** обновление импортов в прототипе (следующая задача), тесты (2.1.6)
**Edge cases:**
- RECIPE_VERSION_V2 используется внутри recipe_engine — проверить нужно ли вынести как параметр или оставить как локальную константу 2 (без import из migrations)
- `gui_state_proxy.py` — TYPE_CHECKING импорт должен быть оставлен как есть
- При добавлении `IStateStoreManager` в качестве базового класса — проверить что `use()` возвращает `IStateStoreManager`, а не `StateStoreManager` (return type annotation)
**Dependencies:** Задача 2.1.2

---

### Задача 2.1.4 — Shim-ы в прототипе + первичная верификация

**Уровень:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** создать shim-файлы в `multiprocess_prototype/state_store/` которые реэкспортируют из fw; проверить что все тесты проходят через shim-ы.
**Context:** Shim-ы — временный мост. После этой задачи прототип работает со старыми импортами, но реализация находится во фреймворке. Это даёт безопасную точку верификации перед финальным переключением.

**Файлы (создать/изменить в прототипе):**
- `multiprocess_prototype/state_store/__init__.py` → shim (переэкспорт из fw)
- `multiprocess_prototype/state_store/core/__init__.py` → shim
- `multiprocess_prototype/state_store/core/delta.py` → shim: `from multiprocess_framework.modules.state_store_module.core.delta import *`
- `multiprocess_prototype/state_store/core/tree_store.py` → shim
- `multiprocess_prototype/state_store/core/subscription_manager.py` → shim
- `multiprocess_prototype/state_store/manager/__init__.py` → shim
- `multiprocess_prototype/state_store/manager/state_store_manager.py` → shim
- `multiprocess_prototype/state_store/manager/delta_dispatcher.py` → shim
- `multiprocess_prototype/state_store/proxy/__init__.py` → shim
- `multiprocess_prototype/state_store/proxy/state_proxy.py` → shim
- `multiprocess_prototype/state_store/proxy/gui_state_proxy.py` → shim
- `multiprocess_prototype/state_store/middleware/__init__.py` → shim
- `multiprocess_prototype/state_store/middleware/base.py` → shim
- `multiprocess_prototype/state_store/middleware/throttle.py` → shim
- `multiprocess_prototype/state_store/middleware/validation.py` → shim
- `multiprocess_prototype/state_store/middleware/logging_mw.py` → shim
- `multiprocess_prototype/state_store/middleware/metrics.py` → shim
- `multiprocess_prototype/state_store/selectors/__init__.py` → shim
- `multiprocess_prototype/state_store/selectors/selector.py` → shim
- `multiprocess_prototype/state_store/devtools/__init__.py` → shim
- `multiprocess_prototype/state_store/devtools/inspector.py` → shim
- `multiprocess_prototype/state_store/health/__init__.py` → shim
- `multiprocess_prototype/state_store/health/monitor.py` → shim
- `multiprocess_prototype/state_store/persistence/__init__.py` → shim
- `multiprocess_prototype/state_store/persistence/persistence_manager.py` → shim
- `multiprocess_prototype/state_store/recipes/__init__.py` → shim
- `multiprocess_prototype/state_store/recipes/recipe_engine.py` → shim (с обёрткой для migration_fn)

**Шаблон shim-файла:**
```python
# SHIM — временный файл. После Задачи 2.1.5 будет удалён.
# Реализация перенесена в multiprocess_framework.modules.state_store_module
from multiprocess_framework.modules.state_store_module.core.delta import *  # noqa: F401, F403
```

**Особый случай — recipe_engine shim:**
```python
# SHIM для RecipeEngine — подключает доменные migration_fn
from multiprocess_framework.modules.state_store_module.recipes.recipe_engine import RecipeEngine as _RecipeEngine
from multiprocess_prototype.state_store.recipes.migrations import migrate_recipe_data, needs_migration

class RecipeEngine(_RecipeEngine):
    """Доменный wrapper: подключает migration_fn автоматически."""
    def __init__(self, store, data_path, **kwargs):
        kwargs.setdefault("migration_fn", migrate_recipe_data)
        kwargs.setdefault("migration_check_fn", needs_migration)
        super().__init__(store, data_path, **kwargs)

__all__ = ["RecipeEngine"]
```

**Шаги:**
1. Создать все shim-файлы (перечислены выше)
2. Запустить: `pytest multiprocess_prototype/state_store/tests/ -v` — все тесты должны пройти
3. Запустить: `pytest multiprocess_prototype/tests/integration/test_state_store_integration.py -v` — 14 тестов должны пройти
4. Запустить: `pytest multiprocess_prototype/tests/unit/test_state_store_config.py -v` — проходит
5. Smoke-проверка: `python -c "from multiprocess_prototype.state_store import StateProxy, StateStoreManager; print('shims OK')"`

**Acceptance criteria:**
- [ ] `pytest multiprocess_prototype/state_store/tests/ -v` — все тесты GREEN
- [ ] `pytest multiprocess_prototype/tests/integration/test_state_store_integration.py -v` — все GREEN
- [ ] `pytest multiprocess_prototype/tests/unit/test_state_store_config.py -v` — GREEN
- [ ] `python scripts/validate.py` — без новых ошибок
- [ ] Все shim-файлы содержат комментарий `# SHIM — будет удалён в Задаче 2.1.5`

**Out of scope:** удаление shim-ов, обновление реальных импортов
**Edge cases:** recipes/recipe_engine.py — специальный shim (класс-обёртка, а не просто `import *`)
**Dependencies:** Задача 2.1.3

---

### Задача 2.1.5 — Замена реальных импортов + удаление shim-ов

**Уровень:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** заменить импорты в 3 файлах прототипа на fw-пути; удалить все shim-файлы; добавить явный `server_target` в точках создания StateProxy.
**Context:** Финальная очистка. После этой задачи в прототипе остаётся только доменный код (bootstrap, adapters, migrations).

**Файлы для обновления импортов:**
- `multiprocess_prototype/backend/processes/camera/process.py:63` — заменить `from multiprocess_prototype.state_store.proxy.state_proxy import StateProxy` → `from multiprocess_framework.modules.state_store_module.proxy import StateProxy`. Добавить `server_target="ProcessManager"` в конструктор явно.
- `multiprocess_prototype/backend/processes/process_manager/process.py:59-68` — заменить 4 lazy import-а (StateStoreManager, build_initial_state, ValidationMiddleware, ThrottleMiddleware) → fw-пути. `build_initial_state` остаётся из `multiprocess_prototype.state_store.bootstrap`.
- `multiprocess_prototype/tests/integration/test_state_store_integration.py` — заменить 4 импорта; `build_initial_state` — из прототипа `state_store.bootstrap`.
- `multiprocess_prototype/state_store/adapters/registers_adapter.py:19` — заменить `from multiprocess_prototype.state_store.core.delta import Delta` → fw-путь
- `multiprocess_prototype/state_store/adapters/camera_state_adapter.py` — аналогично

**Файлы для удаления (все shim-ы из Задачи 2.1.4):**
Удалить все перечисленные shim-файлы кроме:
- `multiprocess_prototype/state_store/__init__.py` — обновить чтобы реэкспортировал из fw (публичный API для обратной совместимости)
- `multiprocess_prototype/state_store/bootstrap.py` — ОСТАВИТЬ (доменный)
- `multiprocess_prototype/state_store/adapters/` — ОСТАВИТЬ (доменный)
- `multiprocess_prototype/state_store/recipes/migrations/v1_to_v2.py` — ОСТАВИТЬ (доменный)

**Шаги:**
1. Обновить `backend/processes/camera/process.py` — изменить lazy import, добавить `server_target="ProcessManager"`
2. Обновить `backend/processes/process_manager/process.py` — изменить 4 lazy imports
3. Обновить `tests/integration/test_state_store_integration.py` — изменить 4 imports
4. Обновить `state_store/adapters/registers_adapter.py` — изменить import Delta
5. Обновить `state_store/adapters/camera_state_adapter.py` — аналогично
6. Удалить все shim-файлы (кроме сохраняемых)
7. Финальный `state_store/__init__.py` — оставить только реэкспорт из fw для обратной совместимости:
   ```python
   # state_store/__init__.py — доменная точка входа.
   # Реализация — в multiprocess_framework.modules.state_store_module
   from multiprocess_framework.modules.state_store_module import *  # noqa
   ```

**Acceptance criteria:**
- [ ] Все shim-файлы удалены (кроме сохраняемых 4)
- [ ] `pytest multiprocess_prototype/state_store/tests/ -v` — все GREEN (теперь тесты запускаются через fw-код напрямую через `__init__.py`)
- [ ] `pytest multiprocess_prototype/tests/integration/test_state_store_integration.py -v` — все 14 GREEN
- [ ] `pytest multiprocess_prototype/tests/unit/ -v` — все GREEN
- [ ] `python -c "from multiprocess_prototype.state_store.bootstrap import build_initial_state; s = build_initial_state({}); print('bootstrap OK')"` — OK
- [ ] `grep -r "from multiprocess_prototype.state_store.core" multiprocess_prototype/backend/` — пустой результат
- [ ] `grep -r "from multiprocess_prototype.state_store.manager" multiprocess_prototype/backend/` — пустой результат
- [ ] `grep -r "from multiprocess_prototype.state_store.proxy" multiprocess_prototype/backend/` — пустой результат
- [ ] `python scripts/validate.py` — без ошибок

**Out of scope:** тесты fw (Задача 2.1.6)
**Edge cases:** `build_initial_state` в тестах integration остаётся из прототипа (она доменная)
**Dependencies:** Задача 2.1.4

---

### Задача 2.1.6 — Перенос тестов во фреймворк

**Уровень:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** переместить generic тесты из `state_store/tests/` в `state_store_module/tests/` с обновлением импортов на fw-пути.
**Context:** По принципу проекта — тесты следуют за кодом. После переноса тесты в прототипе остаются только для доменного кода (adapters, bootstrap, integration).

**Файлы:**
- `state_store/tests/test_delta.py` → `state_store_module/tests/test_delta.py` (обновить импорты)
- `state_store/tests/test_tree_store.py` → fw (обновить импорты)
- `state_store/tests/test_subscription_manager.py` → fw (обновить импорты)
- `state_store/tests/test_state_store_manager.py` → fw (обновить импорты)
- `state_store/tests/test_middleware.py` → fw (обновить импорты)
- `state_store/tests/test_inspector.py` → fw (обновить импорты)
- `state_store/tests/test_persistence.py` → fw (обновить импорты)
- `state_store/tests/test_recipe_engine.py` → fw (обновить импорты + добавить migration_fn в тестах создания RecipeEngine с миграцией)

**Шаги:**
1. Скопировать все 8 файлов тестов в `state_store_module/tests/`
2. В каждом файле заменить: `from multiprocess_prototype.state_store.` → `from multiprocess_framework.modules.state_store_module.`
3. В `test_recipe_engine.py` — тесты миграции: либо mock migration_fn, либо передавать из прототипа `from multiprocess_prototype.state_store.recipes.migrations import migrate_recipe_data, needs_migration`
4. Удалить оригинальные файлы из `state_store/tests/` (или очистить их — оставить пустой `__init__.py`)
5. Создать `state_store/tests/__init__.py` с комментарием "тесты переехали в fw state_store_module/tests/"
6. Запустить fw-тесты: `pytest multiprocess_framework/modules/state_store_module/tests/ -v`
7. Запустить: `python scripts/run_framework_tests.py`

**Acceptance criteria:**
- [ ] `pytest multiprocess_framework/modules/state_store_module/tests/ -v` — все тесты GREEN
- [ ] `python scripts/run_framework_tests.py` — без новых ошибок
- [ ] `state_store/tests/` содержит только `__init__.py` с пояснительным комментарием
- [ ] Все импорты в fw-тестах ссылаются на fw-пути, не на прототип

**Out of scope:** тесты adapters и bootstrap (остаются в прототипе)
**Edge cases:** `test_recipe_engine.py` — тесты миграции должны импортировать migration_fn из прототипа или использовать mock
**Dependencies:** Задача 2.1.5

---

### Задача 2.1.7 — Документация модуля

**Уровень:** Junior (Haiku, normal)
**Assignee:** docs-writer
**Goal:** создать `README.md`, `STATUS.md`, `DECISIONS.md` для нового модуля фреймворка.
**Context:** По правилам проекта: у каждого модуля должны быть README.md, STATUS.md, DECISIONS.md. Это финальная задача фазы.

**Файлы (создать):**
- `multiprocess_framework/modules/state_store_module/README.md`
- `multiprocess_framework/modules/state_store_module/STATUS.md`
- `multiprocess_framework/modules/state_store_module/DECISIONS.md`
- `multiprocess_framework/modules/state_store_module/recipes/migrations/README.md`

**Содержание README.md:**
- Назначение модуля (реактивное дерево состояния для многопроцессных приложений)
- Архитектура (server-side StateStoreManager + client-side StateProxy)
- IPC-протокол (7 команд: state.set, state.merge, state.get, state.get_subtree, state.subscribe, state.unsubscribe, state.unsubscribe_all)
- Быстрый старт: как создать StateStoreManager, как создать StateProxy
- Параметр server_target: зачем нужен, как задавать
- Middleware pipeline: как подключить ValidationMiddleware и ThrottleMiddleware
- Selectors: computed views
- DevTools: StateInspector
- Health: HealthMonitor
- Persistence: PersistenceManager
- Recipes: RecipeEngine + как подключить доменные migration_fn
- **Интеграция с Router:** указать что для интеграции с любым router-ом достаточно реализовать `IRouter` Protocol (3 метода: `register_message_handler`, `send_async`, `send`) — наследование не требуется
- **Самодостаточность:** модуль зависит только от stdlib + опционально PySide6 в GuiStateProxy (lazy import)
- **Тестирование прикладного кода:** раздел с примером использования `InMemoryRouter`:
  ```python
  from multiprocess_framework.modules.state_store_module import (
      StateStoreManager, StateProxy
  )
  from multiprocess_framework.modules.state_store_module.testing import InMemoryRouter

  def test_state_propagation():
      router = InMemoryRouter()
      manager = StateStoreManager(initial_state={"camera": {"status": "idle"}})
      manager.initialize()
      manager.register_message_handlers(router)

      proxy = StateProxy("camera_0", router=router, server_target="ProcessManager")
      router.register_message_handler("state.changed", proxy.on_state_changed)

      proxy.set("camera.status", "running")
      assert proxy.get("camera.status") == "running"
  ```

**Содержание STATUS.md:**
- Текущий статус: STABLE (перенесён из прототипа Фаза 2.1)
- Таблица компонентов: core, manager, proxy, middleware, selectors, devtools, health, persistence, recipes, testing
- TODO: server_target без default (Фаза 4), авто-регистрация state.changed handler (Фаза 4)

**Содержание DECISIONS.md:**
- ADR-SS-001: IRouter Protocol
- ADR-SS-002: Конфигурируемый server_target
- ADR-SS-003: Migration callback в RecipeEngine
- ADR-SS-004: Публичные алиасы match_pattern/split_pattern
- ADR-SS-005: GuiStateProxy — lazy PySide6 import
- ADR-SS-006: TODO авто-регистрация (Фаза 4)
- ADR-SS-007: TODO exclude_self через DeltaDispatcher (уже реализовано)
- ADR-SS-008: Broadcast vs targets — уже адресная доставка
- **ADR-SS-009: ABC для собственных публичных классов, Protocol для внешних зависимостей**
- **ADR-SS-010: testing/ подпакет — InMemoryRouter для прикладных тестов**

**Acceptance criteria:**
- [ ] Все 3 файла созданы
- [ ] README.md содержит быстрый старт с примером кода
- [ ] README.md содержит раздел «Тестирование прикладного кода» с примером InMemoryRouter
- [ ] README.md содержит раздел «Интеграция с Router» с описанием IRouter Protocol
- [ ] DECISIONS.md содержит все 10 ADR (ADR-SS-001...ADR-SS-010)
- [ ] STATUS.md содержит таблицу статусов всех компонентов (включая testing/)

**Out of scope:** обновление глобального DECISIONS.md фреймворка (отдельная задача)
**Edge cases:** нет
**Dependencies:** Задача 2.1.6

---

## Раздел 6: Verification commands

После каждой задачи выполнять проверки:

### После 2.1.0 (скелет + interfaces):
```bash
python -c "
from multiprocess_framework.modules.state_store_module.interfaces import (
    IRouter, IStateStore, IStateProxy, IStateStoreManager
)
print('IRouter OK')
print('IStateStore OK')
print('IStateProxy OK')
print('IStateStoreManager OK')
"
python scripts/validate.py
```

### После 2.1.0a (testing/ подпакет):
```bash
python -c "from multiprocess_framework.modules.state_store_module.testing import InMemoryRouter; r = InMemoryRouter(); print('InMemoryRouter OK')"
python scripts/validate.py
```

### После 2.1.1 (core/):
```bash
python -c "from multiprocess_framework.modules.state_store_module.core import TreeStore, Delta, SubscriptionManager, match_pattern; print('core OK')"
python scripts/validate.py
```

### После 2.1.2 (middleware, selectors, devtools, health, persistence):
```bash
python -c "
from multiprocess_framework.modules.state_store_module.middleware import ValidationMiddleware, ThrottleMiddleware
from multiprocess_framework.modules.state_store_module.health import HealthMonitor
from multiprocess_framework.modules.state_store_module.persistence import PersistenceManager
from multiprocess_framework.modules.state_store_module.devtools import StateInspector
from multiprocess_framework.modules.state_store_module.selectors import Selector
print('middleware+selectors+devtools+health+persistence OK')
"
python scripts/validate.py
```

### После 2.1.3 (manager, proxy, recipes + главный __init__):
```bash
python -c "
from multiprocess_framework.modules.state_store_module import (
    StateStoreManager, StateProxy, GuiStateProxy, RecipeEngine,
    IRouter, IStateStore, IStateProxy, IStateStoreManager,
    InMemoryRouter
)
proxy = StateProxy('test_proc', server_target='ProcessManager')
print('StateProxy server_target OK:', proxy._server_target)
mgr = StateStoreManager()
print('StateStoreManager OK')

# Проверка контрактов (ADR-SS-009)
from multiprocess_framework.modules.state_store_module.core import TreeStore
assert issubclass(TreeStore, IStateStore), 'TreeStore не реализует IStateStore'
assert issubclass(StateProxy, IStateProxy), 'StateProxy не реализует IStateProxy'
assert issubclass(StateStoreManager, IStateStoreManager), 'StateStoreManager не реализует IStateStoreManager'
print('Все ABC-контракты реализованы')

# Проверка InMemoryRouter в __all__
import multiprocess_framework.modules.state_store_module as m
assert 'InMemoryRouter' in m.__all__, 'InMemoryRouter не в __all__'
print('InMemoryRouter в публичном API')

print('ALL OK')
"
python scripts/validate.py
```

### После 2.1.4 (shim-ы):
```bash
# Старые импорты через shim должны работать
python -c "from multiprocess_prototype.state_store import StateProxy, StateStoreManager; print('shims OK')"
pytest multiprocess_prototype/state_store/tests/ -v
pytest multiprocess_prototype/tests/integration/test_state_store_integration.py -v
pytest multiprocess_prototype/tests/unit/test_state_store_config.py -v
python scripts/validate.py
```

### После 2.1.5 (финальные импорты, удаление shim-ов):
```bash
python -c "from multiprocess_prototype.state_store.bootstrap import build_initial_state; s = build_initial_state({}); assert 'system' in s; print('bootstrap OK')"
python -c "from multiprocess_prototype.backend.processes.process_manager.process import ProcessManagerProcessApp; print('PM OK')"
pytest multiprocess_prototype/tests/integration/test_state_store_integration.py -v
pytest multiprocess_prototype/tests/unit/ -v
# Проверяем что нет старых импортов в backend/:
grep -rn "from multiprocess_prototype.state_store.core" multiprocess_prototype/backend/ && echo "FAIL: найдены старые импорты" || echo "OK: старых импортов нет"
grep -rn "from multiprocess_prototype.state_store.proxy" multiprocess_prototype/backend/ && echo "FAIL" || echo "OK"
python scripts/validate.py
```

### После 2.1.6 (тесты переехали в fw):
```bash
pytest multiprocess_framework/modules/state_store_module/tests/ -v
python scripts/run_framework_tests.py
pytest multiprocess_prototype/tests/ -v
```

### После 2.1.7 (документация):
```bash
# Финальная проверка всего
python scripts/validate.py
python scripts/run_framework_tests.py
pytest multiprocess_prototype/tests/ -v
python -c "
from multiprocess_framework.modules.state_store_module import *
from multiprocess_prototype.state_store.bootstrap import build_initial_state
s = build_initial_state({})
store = TreeStore(initial=s)
from multiprocess_framework.modules.state_store_module import StateStoreManager
mgr = StateStoreManager(initial_state=s)
mgr.initialize()
print('FULL VERIFICATION OK')
"
```

---

## Раздел 7: Откат (Rollback)

### Откат после Задачи 2.1.3 или ранее

Задачи 2.1.0, 2.1.0a, 2.1.1-2.1.3 только добавляют файлы во фреймворк. Прототип не трогается. Откат = удаление директории `multiprocess_framework/modules/state_store_module/`:
```bash
rm -rf multiprocess_framework/modules/state_store_module/
git checkout -- multiprocess_prototype/
```

### Откат после Задачи 2.1.4 (shim-ы добавлены)

Shim-ы заменили реализацию в прототипе. Для отката:
1. `git checkout -- multiprocess_prototype/state_store/` — вернуть оригинальные файлы
2. `rm -rf multiprocess_framework/modules/state_store_module/` — удалить fw-модуль

### Откат после Задачи 2.1.5 (реальные импорты обновлены)

Откат сложнее — изменены реальные файлы прототипа:
```bash
git revert HEAD  # или git checkout -- конкретные файлы
```
Рекомендуется делать коммит после каждой задачи для чистого git revert.

### Откат после Задачи 2.1.6 (тесты переехали)

```bash
git revert HEAD  # вернуть тесты в state_store/tests/
```

---

## Раздел 8: Порядок коммитов (рекомендация)

| Задача | Коммит | Что включает |
|---|---|---|
| 2.1.0 | `feat(fw): state_store_module skeleton + IRouter/IStateStore/IStateProxy/IStateStoreManager interfaces` | скелет + interfaces.py (4 контракта) |
| 2.1.0a | `feat(fw): state_store_module testing/ InMemoryRouter` | testing/ подпакет |
| 2.1.1 | `feat(fw): state_store_module core/ (TreeStore(IStateStore), Delta, SubscriptionManager)` | core/ + наследование |
| 2.1.2 | `feat(fw): state_store_module middleware/, selectors/, devtools/, health/, persistence/` | 5 блоков |
| 2.1.3 | `feat(fw): state_store_module manager/, proxy/, recipes/ + ABC-контракты + server_target + migration_fn + __init__` | центральные классы |
| 2.1.4 | `refactor(proto): state_store shims → fw (verification step)` | shim-ы + тесты |
| 2.1.5 | `refactor(proto): state_store replace real imports + remove shims` | финальная замена |
| 2.1.6 | `refactor(tests): state_store tests → fw state_store_module/tests/` | перенос тестов |
| 2.1.7 | `docs(fw): state_store_module README, STATUS, DECISIONS (ADR-SS-001...SS-010)` | документация |

---

## Раздел 9: Риски и митигация

| Риск | Вероятность | Митигация |
|---|---|---|
| `_match_pattern`/`_split_pattern` — публичные алиасы нарушат behaviour | Низкая | Это простые алиасы, поведение не меняется. Покрыто тестами. |
| RecipeEngine migration_fn — кто-то создаёт RecipeEngine в прототипе без adapter | Средняя | Shim-файл рецептов (задача 2.1.4) содержит wrapper с дефолтными migration_fn. После 2.1.5 — проверить grep по RecipeEngine. |
| GuiStateProxy — PySide6 не установлен при тестировании fw | Низкая | lazy import уже в реализации. Тесты без Qt проходили всегда. |
| StateProxy server_target default="ProcessManager" — забыть передать явно | Средняя | Задача 2.1.5 явно требует добавить `server_target="ProcessManager"` в camera/process.py. Тест integration зафиксирует это. |
| Циклические импорты при использовании `from ..core import match_pattern` | Низкая | Граф зависимостей DAG, циклов нет. Проверяется smoke-тестами после каждой задачи. |
| Прерывание в середине (незавершённые shim-ы) | Средняя | Коммит после каждой задачи. Shim-задача атомарна. |

---

## Раздел 10: Итоговая сводка

| Метрика | До Фазы 2.1 | После Фазы 2.1 |
|---|---|---|
| **Строк в state_store/ (прото)** | ~5,800 (generic) + ~400 (domain) | ~400 (domain only) |
| **Строк в state_store_module/ (fw)** | 0 | ~5,400 |
| **Тесты generic в state_store/tests/** | ~7,000 строк, 8 файлов | переехали в fw |
| **Файлов в state_store/ (прото)** | ~30 | 5 (bootstrap + 3 adapters + 1 migration) |
| **Прямых импортёров state_store из бекенда** | 3 файла (~10 import-statements) | 0 (всё через fw) |
| **Hardcoded "ProcessManager" в fw** | N/A | Устранён → `server_target` параметр |
| **IRouter Protocol** | нет | есть |
| **ABC-контракты для публичных классов** | нет | есть (`IStateStore`, `IStateProxy`, `IStateStoreManager`) |
| **testing/ подпакет** | нет | есть (`InMemoryRouter` в публичном API) |
| **RecipeEngine в fw без доменных зависимостей** | нет | есть (migration_fn через параметр) |
