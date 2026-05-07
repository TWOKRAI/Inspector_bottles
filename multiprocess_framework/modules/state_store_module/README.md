# State Store Module

Реактивное иерархическое дерево состояния для многопроцессных приложений (Phase 2.1).

Модуль предоставляет server-side управление глобальным состоянием (`StateStoreManager` в ProcessManager) и client-side кэширование с подписками (`StateProxy` в каждом рабочем процессе). Подписки на glob-паттерны доставляют дельты (изменения) адресно через IPC.

> **Что нового (2026-05-07, рефакторинг 8.0 → 9/10):**
> 1. **Фильтрация callbacks по pattern (ADR-SS-012).** `StateProxy._invoke_callbacks` теперь не передаёт каждому callback все дельты пакета: каждый callback получает только дельты, чьи path реально матчат его pattern. Внешний контракт `subscribe()` не изменился, никаких миграций не требуется — просто callbacks больше не вызываются на «чужих» дельтах.
> 2. **`PersistenceManager` стал доменно-нейтральным (ADR-SS-011).** Жёстко зашитые prefix-ы (`cameras`/`renderer`/`robot`/`database`/`system`) и предикаты `*.state.*`/`system.*` вынесены в параметры конструктора `file_mapping`, `skip_predicate`, `immediate_predicate`. Прикладной код задаёт правила сам — фреймворк больше не знает доменных ветвей.
> 3. **README/STATUS приведены в соответствие с реальным API** (подробности — в разделах ниже).

---

## Архитектура

### Server-side (ProcessManager)

- **TreeStore** — иерархическое дерево состояния (dict). Методы: `get(path)`, `get_subtree(path)`, `set(path, value)`, `merge(path, dict)`, `delete(path)`, `transaction(label)`, `snapshot(paths)`, `restore(data, path)`.
- **SubscriptionManager** — управление glob-подписками (например, `cameras.*.config.*`). Содержит `subscribe(pattern, subscriber, exclude_sources)`, `unsubscribe(sub_id)`, `unsubscribe_all(subscriber)`, `match(delta)`.
- **DeltaDispatcher** — рассылка изменений (Delta) заинтересованным процессам через `targets`, с дедупликацией по subscriber.
- **StateStoreManager** — фасад сервера. Содержит TreeStore + SubscriptionManager + DeltaDispatcher. Регистрирует IPC-обработчики (7 команд).

### Client-side (каждый рабочий процесс)

- **StateProxy** — клиентский прокси. Локально кэширует подписанные пути, общается с сервером через IPC. Методы: `get()`, `set()`, `merge()`, `subscribe()`, `unsubscribe()`, `on_state_changed()`. Каждый callback получает только дельты, попавшие в его pattern (фильтрация на клиенте, ADR-SS-012).
- **GuiStateProxy** — вариант StateProxy для PySide6 GUI-процесса. Импортирует PySide6 лениво (внутри методов).

### IPC-протокол (7 команд + 1 событие)

| Команда | Направление | Назначение |
|---------|------------|-----------|
| `state.set` | client → server | Установить значение по пути |
| `state.merge` | client → server | Слияние dict в поддерево |
| `state.get` | client → server | Получить значение (синхронно) |
| `state.get_subtree` | client → server | Получить поддерево (синхронно) |
| `state.subscribe` | client → server | Подписаться на паттерн |
| `state.unsubscribe` | client → server | Отписаться по sub_id |
| `state.unsubscribe_all` | client → server | Отписаться от всех подписок процесса |
| `state.changed` | server → client(s) | Адресная рассылка дельт подписчикам |

---

## Быстрый старт

### 1. Создать StateStoreManager на сервере (ProcessManager)

```python
from multiprocess_framework.modules.state_store_module import StateStoreManager

# В ProcessManagerProcess
manager = StateStoreManager(
    router=my_router,
    initial_state={"cameras": {}},
    manager_name="StateStoreManager",
)
manager.initialize()  # Регистрирует IPC-обработчики в router
```

### 2. Создать StateProxy на клиенте (рабочий процесс)

```python
from multiprocess_framework.modules.state_store_module import StateProxy

proxy = StateProxy(
    process_name="camera_0",
    router=my_router,
    server_target="ProcessManager",
)

# Регистрируем handler для входящих дельт (ADR-SS-006: авто-регистрация — Фаза 4)
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
        # callback получит ТОЛЬКО дельты, чьи path попадают под pattern
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
# Вариант 1: явно (рекомендуется для ясности)
proxy = StateProxy(
    process_name="camera_0",
    router=router,
    server_target="ProcessManager",
)

# Вариант 2: использовать default (обратная совместимость)
proxy = StateProxy(
    process_name="camera_0",
    router=router,
    # server_target="ProcessManager" — используется по умолчанию
)
```

В Фазе 4 default будет убран — `server_target` станет обязательным параметром (см. ADR-SS-002 TODO).

---

## Интеграция с Router (ADR-SS-001)

Модуль не зависит от конкретного `RouterManager`. Используется Protocol `IRouter` с тремя методами:

```python
@runtime_checkable
class IRouter(Protocol):
    def register_message_handler(
        self, key: str, handler: Callable, expects_full_message: bool = True
    ) -> None: ...

    def send_async(self, message: dict, priority: str = "normal") -> None: ...

    def send(self, message: dict) -> dict | None: ...
```

Любой объект с этими тремя методами совместим. `RouterManager` фреймворка и `InMemoryRouter` для тестов реализуют их без наследования.

---

## Middleware Pipeline

`StateStoreManager` поддерживает middleware для обработки изменений:

```python
from multiprocess_framework.modules.state_store_module import (
    StateStoreManager,
    ThrottleMiddleware,
    ValidationMiddleware,
    LoggingMiddleware,
    MetricsMiddleware,
)

manager = StateStoreManager(router=router, initial_state={})

manager.use(ValidationMiddleware({
    "cameras.*.config.fps":  {"type": int, "min": 1, "max": 120},
    "cameras.*.config.type": {"type": str, "enum": ["webcam", "hikvision"]},
}))
manager.use(ThrottleMiddleware({
    "**.state.actual_fps":   1.0,   # max 1 раз/сек
    "**.state.last_seq":     0,     # полная блокировка
}))
manager.use(LoggingMiddleware(level="DEBUG", exclude_patterns=["**.state.actual_fps"]))
manager.use(MetricsMiddleware())

manager.initialize()
```

Встроенные middleware:
- **ThrottleMiddleware** — дебаунс высокочастотных метрик
- **ValidationMiddleware** — проверка типов / диапазонов / enum-ов
- **LoggingMiddleware** — логирование всех изменений с exclude-фильтром
- **MetricsMiddleware** — счётчики операций

---

## Selectors (вычисляемые представления)

Селекторы — вычисляемые значения, зависящие от паттернов в дереве. При изменении зависимости значение пересчитывается и публикуется в `selectors.{name}`.

```python
from multiprocess_framework.modules.state_store_module import (
    Selector,
    SelectorRegistry,
)

registry = SelectorRegistry(store, subscription_manager=manager.subscription_manager)

avg_fps = Selector(
    name="avg_fps",
    dependencies=["cameras.*.state.actual_fps"],
    compute=lambda values: sum(values.values()) / max(len(values), 1),
)
registry.register(avg_fps)

# Теперь selectors.avg_fps хранится в TreeStore.
# Подписаться на selectors.avg_fps можно через обычный proxy.subscribe(...).

# Получить кэшированное значение:
current = registry.get("avg_fps")

# Recompute триггерится через handle_delta() — DeltaDispatcher вызывает его для дельт.
```

---

## DevTools (инспектор состояния)

`StateInspector` помогает отлаживать состояние:

```python
from multiprocess_framework.modules.state_store_module import StateInspector

inspector = StateInspector(
    store=manager.store,
    subscription_manager=manager.subscription_manager,
    metrics=metrics_middleware,  # опционально
    history_size=200,
)

# Расследование:
print(inspector.inspect("cameras.0"))     # поддерево или конкретное значение
print(inspector.subscriptions())          # все активные подписки
print(inspector.history(limit=20))        # последние 20 дельт (если record_delta вызывался)
print(inspector.history(path_filter="cameras"))
print(inspector.stats())                  # метрики (если MetricsMiddleware подключён)
print(inspector.summary())                # tree_root_keys, subscriptions_total, ...
```

`inspect(path)` принимает только конкретные пути или `None` (всё дерево); glob-паттерны не поддерживаются (для них есть `TreeStore.snapshot([patterns])`).

---

## Health Monitor

`HealthMonitor` отслеживает свежесть state-обновлений по процессам (pull-based, без потоков):

```python
from multiprocess_framework.modules.state_store_module import HealthMonitor

monitor = HealthMonitor(store, heartbeat_timeout=5.0)
monitor.register("camera_0", "cameras.0.state.**")
monitor.register("renderer", "renderer.state.**")

# При каждом state-изменении (обычно из middleware):
monitor.record_activity("cameras.0.state.actual_fps")

# Периодически из main loop / таймера:
health = monitor.check()
# → {"camera_0": "running", "renderer": "unresponsive"}
# Также пишет в store: system.health.<name> и system.health.overall
```

API: `register(name, pattern)`, `unregister(name)`, `record_activity(path)`, `check() -> dict`, `get_health() -> dict`. Callback-ов и `start/stop` нет — `check()` вызывается явно.

---

## Persistence Manager

Сохранение и загрузка веток состояния в YAML с дебаунсом. **Доменно-нейтральный (ADR-SS-011):** маппинг и предикаты задаёт прикладной код.

```python
from pathlib import Path
from multiprocess_framework.modules.state_store_module import PersistenceManager

persistence = PersistenceManager(
    store=tree,
    data_dir=Path("/var/state"),
    debounce_seconds=2.0,
    # Прикладная конфигурация: какие prefix → какие YAML-файлы
    file_mapping={
        "cameras":  "state_cameras.yaml",
        "renderer": "state_renderer.yaml",
        "robot":    "state_robot.yaml",
    },
    # Что НЕ сохранять (runtime-only ветви)
    skip_predicate=lambda p: ".state." in p or p.endswith(".state"),
    # Что сохранять немедленно (в обход debounce)
    immediate_predicate=lambda p: p.startswith("system."),
)

# Подключить middleware
manager.use(persistence.middleware)

# При старте — загрузить
restored = persistence.load()
tree.merge("", restored, source="bootstrap")

# При завершении — гарантированный сброс dirty
persistence.shutdown()
```

Без `file_mapping` менеджер не сохраняет ничего (полностью no-op).

---

## Recipes (снимки и миграции)

`RecipeEngine` создаёт снимки конфигурации в YAML и восстанавливает их через `Transaction` (один batch подписчикам).

```python
from pathlib import Path
from multiprocess_framework.modules.state_store_module import RecipeEngine

# Опциональные доменные миграции — callback-и (ADR-SS-003)
def needs_migration(data: dict) -> bool:
    return "old_field" in data

def migrate_v1_to_v2(data: dict) -> dict:
    return {"new_field": data.get("old_field"), **data}

recipe = RecipeEngine(
    store=tree,
    recipes_dir=Path("/var/recipes"),
    migration_fn=migrate_v1_to_v2,
    migration_check_fn=needs_migration,
    recipe_version=2,
)

# Сохранить
recipe.save("default")                            # snapshot всех DEFAULT_CONFIG_PATHS
recipe.save("only_cams", paths=["cameras.0.regions"])  # частичный snapshot

# Загрузить
deltas = recipe.load("default")
deltas = recipe.load("default", remap={"cameras.0": "cameras.1"})

# Управление
names = recipe.list()           # ["default", "only_cams", ...]
active = recipe.get_active()    # имя последнего загруженного
dirty = recipe.is_dirty()       # config изменился после load?
diff = recipe.diff("default")   # [(path, current, recipe_value), ...]
recipe.delete("only_cams")
```

---

## Тестирование прикладного кода (ADR-SS-010)

Для unit-тестов используйте `InMemoryRouter` — встроенный mock роутера:

```python
from multiprocess_framework.modules.state_store_module import (
    InMemoryRouter,
    StateStoreManager,
    StateProxy,
)

def test_camera_config_update():
    router = InMemoryRouter()
    manager = StateStoreManager(router=router, initial_state={})
    manager.initialize()

    proxy = StateProxy(
        process_name="camera_0",
        router=router,
        server_target="ProcessManager",
    )
    router.register_message_handler("state.changed", proxy.on_state_changed)

    proxy.set("cameras.0.fps", 30)
    assert proxy.get("cameras.0.fps") == 30
    assert manager.store.get("cameras.0.fps") == 30
```

`InMemoryRouter` реализует `IRouter` Protocol и работает синхронно в памяти процесса.

---

## Содержание папок

```
state_store_module/
├── __init__.py                    # Публичный API
├── interfaces.py                  # IRouter, IStateStore, IStateProxy, IStateStoreManager
│
├── core/                          # Ядро: дерево, дельты, подписки
│   ├── __init__.py                # TreeStore, Delta, Transaction, MISSING,
│   │                              # SubscriptionManager, Subscription,
│   │                              # match_pattern, split_pattern
│   ├── tree_store.py              # TreeStore (реализует IStateStore)
│   ├── delta.py                   # Delta + Transaction (один файл)
│   └── subscription_manager.py    # SubscriptionManager + glob-матчер
│
├── manager/                       # Server-side
│   ├── state_store_manager.py     # StateStoreManager (реализует IStateStoreManager)
│   └── delta_dispatcher.py        # DeltaDispatcher
│
├── proxy/                         # Client-side
│   ├── state_proxy.py             # StateProxy (реализует IStateProxy)
│   └── gui_state_proxy.py         # GuiStateProxy (lazy PySide6, Qt-thread-safe)
│
├── middleware/                    # Middleware pipeline
│   ├── base.py                    # StateMiddleware (ABC), MiddlewarePipeline
│   ├── throttle.py                # ThrottleMiddleware
│   ├── validation.py              # ValidationMiddleware
│   ├── logging_mw.py              # LoggingMiddleware
│   └── metrics.py                 # MetricsMiddleware
│
├── selectors/                     # Вычисляемые представления
│   └── selector.py                # Selector + SelectorRegistry
│
├── devtools/                      # Инспектор для отладки
│   └── inspector.py               # StateInspector
│
├── health/                        # Мониторинг здоровья
│   └── monitor.py                 # HealthMonitor + WatchedProcess
│
├── persistence/                   # Сохранение и загрузка
│   └── persistence_manager.py     # PersistenceManager + PersistenceMiddleware
│
├── recipes/                       # Снимки и миграции
│   ├── recipe_engine.py           # RecipeEngine
│   └── migrations/                # Место для generic миграций (README.md)
│
├── testing/                       # Public testing helpers (ADR-SS-010)
│   ├── in_memory_router.py        # InMemoryRouter (реализует IRouter)
│   └── README.md
│
├── tests/                         # Unit-тесты модуля (~421 теста)
│   ├── test_tree_store.py
│   ├── test_delta.py
│   ├── test_subscription_manager.py
│   ├── test_core_integration.py
│   ├── test_state_store_manager.py
│   ├── test_state_proxy.py        # включая фильтрацию callbacks
│   ├── test_middleware.py
│   ├── test_throttle.py
│   ├── test_validation.py
│   ├── test_logging_metrics.py
│   ├── test_selectors.py
│   ├── test_inspector.py
│   ├── test_health.py
│   ├── test_persistence.py        # включая custom mapping
│   └── test_recipe_engine.py
│
├── STATUS.md                      # Статус компонентов
└── DECISIONS.md                   # Архитектурные решения (ADR-SS-001..012)
```

---

## Зависимости

Модуль зависит только от:
- **Python 3.12+** (stdlib + `pyyaml`)
- **PySide6** (опционально, для `GuiStateProxy` — ленивый импорт)
- `multiprocess_framework.modules.base_manager` (BaseManager + ObservableMixin)

Модуль НЕ зависит от:
- `RouterManager` (используется Protocol `IRouter`)
- Доменных интеграций (миграции, валидация, prefix-маппинги — задаются прикладным кодом)

---

## Резюме

- **Server-side:** TreeStore + SubscriptionManager + DeltaDispatcher = `StateStoreManager`
- **Client-side:** `StateProxy` (или `GuiStateProxy`) = локальный кэш + IPC + per-pattern фильтрация callbacks
- **IPC:** 7 команд + событие `state.changed` с адресной доставкой
- **Расширяемость:** Middleware (4 встроенных), Selectors, DevTools, Health, Persistence, Recipes
- **Тестирование:** `InMemoryRouter` встроен в публичный API
- **Доменно-нейтральный:** Persistence-маппинги и Recipe-миграции передаются через параметры
