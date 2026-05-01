# State Store Module

Реактивное иерархическое дерево состояния для многопроцессных приложений (Phase 2.1).

Модуль предоставляет server-side управление глобальным состоянием (`StateStoreManager` в ProcessManager) и client-side кэширование с подписками (`StateProxy` в каждом рабочем процессе). Подписки на glob-паттерны доставляют дельты (изменения) адресно через IPC.

---

## Архитектура

### Server-side (ProcessManager)

- **TreeStore** — иерархическое дерево состояния (dict). Методы: `get(path)`, `get_subtree(path)`, `set(path, value)`, `merge(path, dict)`, `delete(path)`.
- **SubscriptionManager** — управление glob-подписками (например, `cameras.*.config.*`). Содержит методы `subscribe(pattern, exclude_sources)` и `match(path)` для поиска подходящих подписчиков.
- **DeltaDispatcher** — рассылка изменений (Delta) заинтересованным процессам через `targets`.
- **StateStoreManager** — фасад сервера. Содержит TreeStore + SubscriptionManager + DeltaDispatcher. Регистрирует IPC-обработчики (7 команд).

### Client-side (каждый рабочий процесс)

- **StateProxy** — клиентский прокси. Локально кэширует подписанные пути, общается с сервером через IPC. Методы: `get()`, `set()`, `merge()`, `subscribe()`, `unsubscribe()`.
- **GuiStateProxy** — вариант StateProxy для PySide6 GUI-процесса. Импортирует PySide6 лениво (внутри методов).

### IPC-протокол (7 команд)

| Команда | Направление | Назначение |
|---------|------------|-----------|
| `state.set` | client → server | Установить значение по пути |
| `state.merge` | client → server | Слияние dict в поддерево |
| `state.get` | client → server | Получить значение (синхронно) |
| `state.get_subtree` | client → server | Получить поддерево (синхронно) |
| `state.subscribe` | client → server | Подписаться на паттерн |
| `state.unsubscribe` | client → server | Отписаться по sub_id |
| `state.unsubscribe_all` | client → server | Отписаться от всех подписок |

Server отправляет:

| Сообщение | Направление | Назначение |
|-----------|------------|-----------|
| `state.changed` | server → client(s) | Адресная рассылка дельт подписчикам |

---

## Быстрый старт

### 1. Создать StateStoreManager на сервере (ProcessManager)

```python
from multiprocess_framework.modules.state_store_module import (
    StateStoreManager,
    TreeStore,
)
from my_router import MyRouter

# В ProcessManagerProcess
store = TreeStore()
manager = StateStoreManager(
    process_name="ProcessManager",
    store=store,
    router=my_router,
)
manager.initialize()  # Регистрирует IPC-обработчики
```

### 2. Создать StateProxy на клиенте (рабочий процесс)

```python
from multiprocess_framework.modules.state_store_module import StateProxy

# В каждом рабочем ProcessModule
proxy = StateProxy(
    process_name="camera_0",
    router=my_router,
    server_target="ProcessManager",  # адресуется к ProcessManager
)

# Регистрируем handler для входящих дельт (вручную, см. ADR-SS-006)
my_router.register_message_handler("state.changed", proxy.on_state_changed)
```

### 3. Использовать в коде

```python
# Запись
proxy.set("cameras.0.fps", 30)
proxy.merge("cameras.0.config", {"resolution": "1080p", "codec": "h264"})

# Чтение (из локального кэша или синхронно с сервера)
fps = proxy.get("cameras.0.fps")
subtree = proxy.get_subtree("cameras.0")

# Подписка на изменения
def on_config_changed(deltas):
    for delta in deltas:
        print(f"Изменилось: {delta.path} = {delta.new_value}")

sub_id = proxy.subscribe(
    pattern="cameras.*.config.*",
    callback=on_config_changed,
    exclude_self=False,  # получать свои изменения
)

# Отписка
proxy.unsubscribe(sub_id)
```

---

## Параметр server_target (ADR-SS-002)

При создании `StateProxy` параметр `server_target` указывает имя процесса, на котором живёт `StateStoreManager`:

```python
# Вариант 1: явно передать (рекомендуется для ясности)
proxy = StateProxy(
    process_name="camera_0",
    router=router,
    server_target="ProcessManager",  # конкретный адрес
)

# Вариант 2: использовать default (обратная совместимость)
proxy = StateProxy(
    process_name="camera_0",
    router=router,
    # server_target="ProcessManager" — используется по умолчанию
)
```

**Примечание:** В Фазе 4 (при рефакторинге лончера) default будет убран — `server_target` станет обязательным параметром (см. ADR-SS-006, TODO).

---

## Интеграция с Router (ADR-SS-001)

Модуль не зависит от конкретного `RouterManager`. Вместо этого используется Protocol `IRouter`, который имеет три метода:

```python
@runtime_checkable
class IRouter(Protocol):
    def register_message_handler(
        self, key: str, handler: Callable, expects_full_message: bool = True
    ) -> None: ...

    def send_async(self, message: dict, priority: str = "normal") -> None: ...

    def send(self, message: dict) -> dict | None: ...
```

Это означает:
- **Наследование не требуется** — достаточно реализовать эти три метода.
- **RouterManager фреймворка** уже реализует этот Protocol без изменений.
- **MockRouter для тестов** тоже должен реализовать эти методы.

Пример для собственного router-а:

```python
class MyRouter:
    def register_message_handler(self, key: str, handler, expects_full_message: bool = True) -> None:
        # ... ваша реализация
        pass

    def send_async(self, message: dict, priority: str = "normal") -> None:
        # ... ваша реализация
        pass

    def send(self, message: dict) -> dict | None:
        # ... ваша реализация
        pass

# StateStoreManager сразу же работает с MyRouter
manager = StateStoreManager(
    process_name="ProcessManager",
    store=store,
    router=my_router,  # MyRouter реализует IRouter
)
```

---

## Middleware Pipeline

StateStoreManager поддерживает middleware для обработки изменений:

```python
from multiprocess_framework.modules.state_store_module import (
    StateStoreManager,
    ThrottleMiddleware,
    ValidationMiddleware,
)

manager = StateStoreManager(process_name="ProcessManager", store=store, router=router)

# Подключить middleware
manager.use(ThrottleMiddleware(delay=0.5))  # Дебаунс изменений на 0.5 сек
manager.use(ValidationMiddleware(schemas={"cameras.*": CameraSchema}))  # Валидация

manager.initialize()
```

Встроенные middleware:
- **ThrottleMiddleware** — группировка и дебаунс дельт
- **ValidationMiddleware** — проверка типов перед применением
- **LoggingMiddleware** — логирование всех изменений
- **MetricsMiddleware** — сбор статистики

---

## Selectors (вычисляемые представления)

Селекторы позволяют определить вычисляемые представления состояния:

```python
from multiprocess_framework.modules.state_store_module import (
    Selector,
    SelectorRegistry,
)

registry = SelectorRegistry(store)

# Определить селектор
@registry.register("active_cameras_count")
def count_active(state):
    cameras = state.get_subtree("cameras") or {}
    return len([c for c in cameras.values() if c.get("active", False)])

# Использовать
count = registry.get("active_cameras_count")  # = 2
```

---

## DevTools (инспектор состояния)

StateInspector помогает отлаживать состояние:

```python
from multiprocess_framework.modules.state_store_module import StateInspector

inspector = StateInspector(manager)

print(inspector.inspect("cameras.*"))  # показать все камеры
print(inspector.subscriptions())  # список активных подписок
print(inspector.history(limit=20))  # последние 20 изменений
print(inspector.stats())  # статистика
```

---

## Health Monitor

HealthMonitor отслеживает здоровье дерева состояния:

```python
from multiprocess_framework.modules.state_store_module import HealthMonitor

monitor = HealthMonitor(manager)
monitor.add_watchdog(
    pattern="cameras.*.status",
    timeout=5.0,
    callback=lambda: print("Камера не обновляет статус!"),
)
monitor.start()

# ... позже
monitor.stop()
```

---

## Persistence Manager

Сохранение и загрузка состояния в YAML с дебаунсом:

```python
from pathlib import Path
from multiprocess_framework.modules.state_store_module import PersistenceManager

persistence = PersistenceManager(
    store=store,
    data_path=Path("/tmp/state.yaml"),
    debounce_delay=2.0,  # сохранять максимум раз в 2 сек
)

persistence.start()  # запустить воркер

# ... изменения сохраняются автоматически

persistence.stop()
```

---

## Recipes (снимки и миграции)

RecipeEngine позволяет создавать снимки состояния и восстанавливаться из них:

```python
from multiprocess_framework.modules.state_store_module import RecipeEngine

# Функции миграции (из прикладного кода)
def migrate_recipe_v1_to_v2(data):
    # трансформация старого формата в новый
    return data

def needs_migration(data):
    # проверка, нужна ли миграция
    return data.get("version") == 1

# Создать RecipeEngine
recipe = RecipeEngine(
    store=store,
    data_path=Path("/tmp/recipes"),
    migration_fn=migrate_recipe_v1_to_v2,
    migration_check_fn=needs_migration,
)

# Снимок
recipe.snapshot("my_snapshot")

# Восстановление
recipe.restore("my_snapshot")
```

ADR-SS-003: RecipeEngine не знает о доменных миграциях — они передаются через параметры конструктора. Это делает движок переиспользуемым.

---

## Тестирование прикладного кода (ADR-SS-010)

Для unit-тестов используйте `InMemoryRouter` — встроенный mock роутера:

```python
from multiprocess_framework.modules.state_store_module import (
    InMemoryRouter,
    StateStoreManager,
    StateProxy,
    TreeStore,
)

def test_camera_config_update():
    # Создать server
    router = InMemoryRouter()
    store = TreeStore()
    manager = StateStoreManager(
        process_name="ProcessManager",
        store=store,
        router=router,
    )
    manager.initialize()

    # Создать client
    proxy = StateProxy(
        process_name="camera_0",
        router=router,
        server_target="ProcessManager",
    )

    # Регистрировать handler
    router.register_message_handler("state.changed", proxy.on_state_changed)

    # Тестировать
    proxy.set("cameras.0.fps", 30)
    assert proxy.get("cameras.0.fps") == 30
    assert store.get("cameras.0.fps") == 30
```

`InMemoryRouter` реализует `IRouter` Protocol и работает синхронно в памяти процесса.

---

## Содержание папок

```
state_store_module/
├── __init__.py                    # Публичный API
├── interfaces.py                  # IRouter, IStateStore, IStateProxy, IStateStoreManager
│
├── core/                           # Ядро: дерево, дельты, транзакции
│   ├── __init__.py               # Экспорт TreeStore, Delta, Transaction, match_pattern, split_pattern
│   ├── tree_store.py             # TreeStore (реализует IStateStore)
│   ├── delta.py                  # Delta (единица изменения)
│   ├── transaction.py            # Transaction (batch изменений)
│   └── subscription_manager.py   # SubscriptionManager, Subscription, _match_pattern, _split_pattern
│
├── manager/                        # Server-side: StateStoreManager, DeltaDispatcher
│   ├── __init__.py               # StateStoreManager, DeltaDispatcher
│   ├── state_store_manager.py    # StateStoreManager (реализует IStateStoreManager)
│   └── delta_dispatcher.py       # DeltaDispatcher
│
├── proxy/                          # Client-side: StateProxy, GuiStateProxy
│   ├── __init__.py               # StateProxy, GuiStateProxy
│   ├── state_proxy.py            # StateProxy (реализует IStateProxy)
│   └── gui_state_proxy.py        # GuiStateProxy (lazy PySide6 import)
│
├── middleware/                     # Middleware pipeline
│   ├── __init__.py               # Middleware, MiddlewarePipeline
│   ├── base.py                   # StateMiddleware (ABC), MiddlewarePipeline
│   ├── throttle.py               # ThrottleMiddleware
│   ├── validation.py             # ValidationMiddleware
│   ├── logging_mw.py             # LoggingMiddleware
│   └── metrics.py                # MetricsMiddleware
│
├── selectors/                      # Вычисляемые представления
│   ├── __init__.py               # Selector, SelectorRegistry
│   └── registry.py               # SelectorRegistry
│
├── devtools/                       # Инспектор для отладки
│   ├── __init__.py               # StateInspector
│   └── inspector.py              # StateInspector
│
├── health/                         # Мониторинг здоровья
│   ├── __init__.py               # HealthMonitor, WatchedProcess
│   └── monitor.py                # HealthMonitor
│
├── persistence/                    # Сохранение и загрузка
│   ├── __init__.py               # PersistenceManager
│   └── persistence_manager.py    # PersistenceManager (YAML, debounce)
│
├── recipes/                        # Снимки и миграции состояния
│   ├── __init__.py               # RecipeEngine
│   ├── recipe_engine.py          # RecipeEngine (snapshot, restore)
│   └── migrations/               # Место для generic миграций (README.md)
│
├── testing/                        # Public testing helpers (ADR-SS-010)
│   ├── __init__.py               # InMemoryRouter
│   ├── in_memory_router.py       # InMemoryRouter (реализует IRouter)
│   └── README.md                 # Примеры использования
│
├── tests/                          # Unit-тесты модуля
│   ├── test_tree_store.py        # TreeStore
│   ├── test_delta.py             # Delta, Transaction
│   ├── test_state_store_manager.py # StateStoreManager
│   ├── test_state_proxy.py       # StateProxy
│   ├── test_middleware.py        # Middleware pipeline
│   ├── test_selectors.py         # Selectors
│   ├── test_devtools.py          # StateInspector
│   ├── test_health.py            # HealthMonitor
│   ├── test_persistence.py       # PersistenceManager
│   ├── test_recipes.py           # RecipeEngine
│   ├── test_delta_dispatcher.py  # DeltaDispatcher
│   └── test_in_memory_router.py  # InMemoryRouter
│
└── STATUS.md                       # Статус компонентов
└── DECISIONS.md                    # Архитектурные решения (ADR)
```

---

## Зависимости

Модуль зависит только от:
- **Python 3.12+** (stdlib: `abc`, `threading`, `multiprocessing`, `pathlib`, `typing`, `pydantic`)
- **PySide6** (опционально, для `GuiStateProxy` — ленивый импорт)

Модуль НЕ зависит от:
- `RouterManager` (используется Protocol `IRouter`)
- Доменных интеграций (миграции, валидация)

---

## Резюме

- **Server-side:** TreeStore + SubscriptionManager + DeltaDispatcher = StateStoreManager
- **Client-side:** StateProxy (или GuiStateProxy) = локальный кэш + IPC
- **IPC:** 7 команд + adressed delivery через `targets`
- **Расширяемость:** Middleware, Selectors, DevTools, Health, Persistence
- **Тестирование:** InMemoryRouter встроен в публичный API
- **Миграции:** RecipeEngine принимает callback-и, не знает о доменных правилах

