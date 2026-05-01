# state_store_module — архитектурные решения (ADR)

---

## ADR-SS-001: IRouter Protocol для инкапсуляции router-зависимости

**Контекст:** StateProxy, StateStoreManager и DeltaDispatcher требуют router для отправки IPC-сообщений. При разработке в прототипе они импортировали RouterManager напрямую через утиный тип (`router: Any`). При переносе модуля во фреймворк импорт RouterManager создаёт круговую зависимость: state_store_module ← router_module ← process_module ← state_store_module (через ProcessManagerProcess).

**Решение:** Определить `IRouter` как Protocol с тремя методами: `register_message_handler`, `send_async`, `send`. Аннотации StateProxy и StateStoreManager меняют тип с `router: Any` на `router: IRouter | None`. RouterManager фреймворка (прототипа) уже реализует этот контракт без изменений благодаря утиной типизации.

```python
@runtime_checkable
class IRouter(Protocol):
    def register_message_handler(
        self, key: str, handler: Callable, expects_full_message: bool = True
    ) -> None: ...
    def send_async(self, message: dict, priority: str = "normal") -> None: ...
    def send(self, message: dict) -> dict | None: ...
```

**Последствия:**
- Модуль independent от конкретной реализации router-а (обратная совместимость)
- Protocol выполняет роль контракта для любых router-ов (в т.ч. mock-ов в тестах)
- InMemoryRouter для тестов тоже реализует IRouter явно

**Связанные решения:** ADR-SS-010 (InMemoryRouter)

---

## ADR-SS-002: Конфигурируемый server_target в StateProxy

**Контекст:** В прототипе StateProxy содержал модульную константу `_PROCESS_MANAGER = "ProcessManager"`, которая жёстко привязывала client-side прокси к определённому server-side процессу. Это нарушает принцип "фреймворк не знает о доменной архитектуре приложения". После переноса во фреймворк фреймворк не должен предполагать имена процессов.

**Решение:** Убрать модульную константу. Добавить параметр `server_target` в конструктор StateProxy:

```python
def __init__(
    self,
    process_name: str,
    router: IRouter | None = None,
    server_target: str = "ProcessManager",  # default для совместимости
) -> None:
    self._server_target = server_target
    # ...
```

Все пять методов, которые формируют IPC-сообщения (set, merge, get, get_subtree, subscribe), теперь используют `self._server_target` как адрес `"targets"` в сообщении.

**Последствия:**
- Прикладной код явно указывает, к какому server-side процессу обращаться
- Ясность намерений: читатель понимает, на кого идёт запрос
- **Обратная совместимость:** default="ProcessManager" оставлен для гладкой миграции
- **TODO Фаза 4:** убрать default, сделать server_target обязательным параметром

**Примеры обновления в прототипе:**
- `backend/processes/camera/process.py:65` — передать явно
- Интеграционные тесты — добавить явное указание

**Связанные решения:** ADR-SS-001 (server_target адресует через router)

---

## ADR-SS-003: migration_fn и migration_check_fn как параметры RecipeEngine

**Контекст:** RecipeEngine в прототипе импортировал функции миграции из `state_store/recipes/migrations/v1_to_v2.py` (доменная зависимость). При переносе во фреймворк фреймворк не должен знать о доменных правилах миграции рецептов.

**Решение:** RecipeEngine принимает миграции как callback-параметры:

```python
def __init__(
    self,
    store: IStateStore,
    data_path: Path | str,
    migration_fn: Callable[[dict], dict] | None = None,
    migration_check_fn: Callable[[dict], bool] | None = None,
) -> None:
    self._migration_fn = migration_fn
    self._migration_check_fn = migration_check_fn
    # ...

def load(self, name: str) -> dict:
    # ...
    if self._migration_check_fn and self._migration_check_fn(data):
        data = self._migration_fn(data)
    return data
```

В прототипе при создании RecipeEngine (в `recipe_adapter.py`) передаются функции из `recipes/migrations/v1_to_v2.py`:

```python
recipe = RecipeEngine(
    store=store,
    data_path=recipes_dir,
    migration_fn=migrate_recipe_data,
    migration_check_fn=needs_migration,
)
```

**Структура в фреймворке:**
- `state_store_module/recipes/migrations/` создан как место для generic миграций (если появятся)
- Доменные миграции остаются в прототипе: `multiprocess_prototype/state_store/recipes/migrations/v1_to_v2.py`

**Последствия:**
- RecipeEngine generic и переиспользуемый
- Доменная логика полностью в ответственности приложения
- Простое тестирование: миграции передаются в тесте как нужно

**Связанные решения:** ADR-SS-009 (RecipeEngine как компонент фреймворка, но без доменных зависимостей)

---

## ADR-SS-004: Публичные хелперы match_pattern и split_pattern

**Контекст:** HealthMonitor, middleware (throttle, validation, logging) требуют работать с glob-паттернами. Они импортировали приватные функции `_match_pattern` и `_split_pattern` из `core/subscription_manager.py` (двойное подчёркивание = приватная API).

**Решение:** Оставить реализацию в `core/subscription_manager.py` с приватными именами (`_match_pattern`, `_split_pattern`). Дополнительно экспортировать публичные алиасы через `core/__init__.py`:

```python
# core/__init__.py
from .subscription_manager import _match_pattern as match_pattern
from .subscription_manager import _split_pattern as split_pattern
```

Обновить импорты в модулях:
```python
# В health/monitor.py, middleware/*.py
from ...core import match_pattern, split_pattern  # не из subscription_manager
```

**Последствия:**
- Публичная API для работы с паттернами (использование не в скрытых местах)
- Реализация остаётся приватной (может меняться внутри)
- Читаемость кода повышается: явное экспортирование через `__init__.py`

**Связанные решения:** ADR-SS-001 (инкапсуляция через Protocol, здесь инкапсуляция через `__init__.py`)

---

## ADR-SS-005: GuiStateProxy с ленивым импортом PySide6

**Контекст:** GuiStateProxy — вариант StateProxy для GUI-процессов. PySide6 — опциональная зависимость фреймворка (есть только в frontend_module и том, кто её использует).

**Решение:** GuiStateProxy импортирует PySide6 только внутри методов, а не на верхнем уровне. На верхнем уровне — только `TYPE_CHECKING` импорт:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtCore import QObject, Signal

class GuiStateProxy(StateProxy):
    def emit_signal(self, signal_name: str, *args):
        from PySide6.QtCore import QObject, Signal  # ленивый импорт
        # ...
```

**Последствия:**
- GuiStateProxy можно импортировать из модуля на non-GUI машинах (без PySide6)
- Фактический импорт PySide6 происходит только если вызвать методы GuiStateProxy
- Сохраняется self-contained архитектура (state_store_module не требует frontend_module)

**Связанные решения:** ADR-SS-001 (модуль не зависит от конкретных интеграций)

---

## ADR-SS-006: TODO Фаза 4 — авто-регистрация handler-а state.changed

**Контекст:** В Фазе 2.1 каждый рабочий процесс явно регистрирует handler для входящих дельт:

```python
router.register_message_handler("state.changed", proxy.on_state_changed)
```

Это требует от разработчика помнить о регистрации и добавлять строку в каждый процесс.

**Решение (TODO):** В Фазе 4 при рефакторинге ProcessModule:
- ProcessModule будет принимать опциональный `state_proxy: IStateProxy | None`
- При инициализации ProcessModule автоматически регистрирует handler если proxy задан
- Разработчик просто создаёт proxy, не думая о регистрации

```python
# Фаза 4 (target):
class ProcessModule:
    def initialize(self):
        if self._state_proxy:
            self.router.register_message_handler(
                "state.changed",
                self._state_proxy.on_state_changed,
            )
```

**Причина откладывания:** Требует изменения ProcessModule (базовый класс фреймворка), а не только state_store_module.

**Последствия:** Упрощение интеграции для разработчика, прозрачность управления подписками.

---

## ADR-SS-007: exclude_self логика в DeltaDispatcher.match()

**Контекст:** Если process-A изменил значение в состоянии, он может не хотеть получать собственное изменение (exclude_self=True). Серверная логика должна это учитывать.

**Решение:** DeltaDispatcher.match() при построении списка подписчиков для отправки дельты проверяет:
- Подписка паттерна подходит пути (glob-match)
- Если `subscription.exclude_sources` содержит `delta.source` — пропустить эту подписку
- `delta.source` заполняется client-ом при set/merge операции (process_name)

```python
def match(self, delta: Delta) -> list[Subscription]:
    matched = []
    for sub in self._subscriptions:
        if match_pattern(sub.pattern, delta.path):
            # Проверить exclude_sources
            if delta.source not in sub.exclude_sources:
                matched.append(sub)
    return matched
```

**Последствия:** Правильное фильтрование на server-side, редакция не получает собственные дельты если просил.

**Не требуется изменений:** Логика уже реализована в Фазе 2.1 (ADR подтверждает существующий подход).

---

## ADR-SS-008: Адресная доставка (targets) vs broadcast

**Контекст:** DeltaDispatcher рассылает дельты подписчикам. Два подхода:
1. **Broadcast:** отправить всем процессам, пусть сами фильтруют
2. **Адресная доставка:** на сервере определить, кто должен получить, отправить только им

**Решение:** Использовать адресную доставку через поле `targets` в IPC-сообщении:

```python
def dispatch(self, delta: Delta) -> None:
    matched_subs = self.match(delta)  # фильтруем на сервере
    targets = [sub.subscriber for sub in matched_subs]
    
    if targets:
        message = {
            "command": "state.changed",
            "data": {"deltas": [delta.to_dict()]},
            "targets": targets,  # адресная доставка
        }
        self._router.send_async(message, priority="normal")
```

RouterManager получает это и роутит точечно (не broadcast).

**Последствия:**
- Меньше трафика (не отправляем лишние сообщения)
- Меньше CPU на фильтруемые дельты на client-ах
- Более предсказуемая доставка

**Не требуется изменений:** Логика уже реализована в Фазе 2.1.

---

## ADR-SS-009: ABC для собственных публичных классов, Protocol для внешних зависимостей

**Контекст:** При разработке фреймворка контрактов должно быть два типа:
1. **Внешние зависимости** (типа RouterManager) — Protocol + @runtime_checkable (утиная типизация, любой кто реализует методы)
2. **Собственные публичные классы** (типа TreeStore) — ABC с @abstractmethod (явный контракт, mock-friendly)

Эталон `process_manager_module` использует оба подхода: `IRouter` (Protocol) + `ISystemLauncher`, `IProcessManagerProcess`, `IProcessRegistry` (ABC).

**Решение:** В `interfaces.py` state_store_module:

**Внешние зависимости — Protocol:**
```python
@runtime_checkable
class IRouter(Protocol):  # утиная типизация
    def register_message_handler(...): ...
    def send_async(...): ...
    def send(...): ...
```

**Собственные классы — ABC:**
```python
class IStateStore(ABC):
    @abstractmethod
    def get(self, path: str, ...) -> Any: ...
    @abstractmethod
    def set(self, path: str, value: Any, ...) -> Delta | None: ...
    # ...

class IStateProxy(ABC):
    @abstractmethod
    def get(self, path: str, ...) -> Any: ...
    @abstractmethod
    def subscribe(self, pattern: str, ...) -> str: ...
    # ...

class IStateStoreManager(ABC):
    @abstractmethod
    def initialize(self) -> bool: ...
    @abstractmethod
    def register_message_handlers(self, router: IRouter) -> None: ...
    # ...
```

Реализации наследуют контракты:
```python
class TreeStore(IStateStore):
    def get(self, path: str, default=None) -> Any:
        # реализация
        pass
    # ...

class StateProxy(IStateProxy):
    def get(self, path: str, default=None) -> Any:
        # реализация
        pass
    # ...

class GuiStateProxy(StateProxy):  # наследует IStateProxy через StateProxy
    # ...

class StateStoreManager(IStateStoreManager):
    def initialize(self) -> bool:
        # реализация
        pass
    # ...
```

**Последствия:**
- Mock-friendly тесты: можно создать MockStateStore(IStateStore) для тестирования DeltaDispatcher
- Явный публичный API: контрактом задаётся, что гарантирует модуль
- Единообразие с другими модулями фреймворка
- Статическая проверка типов работает корректно
- Обратная совместимость: добавление наследования не меняет реализацию методов

---

## ADR-SS-010: testing/ подпакет — InMemoryRouter для прикладных тестов

**Контекст:** В прототипе `MockBus` (~50 строк) определён внутри `tests/integration/test_state_store_integration.py`. Любой прикладной код, использующий StateProxy в unit-тестах, вынужден либо копировать MockBus, либо использовать интеграционный тест.

**Решение:** Вынести mock-реализацию в публичный API модуля как `InMemoryRouter` (реализует `IRouter` Protocol):

```
state_store_module/testing/
├── __init__.py
├── in_memory_router.py  # InMemoryRouter (реализует IRouter)
└── README.md            # примеры использования
```

InMemoryRouter в `__init__.py`:
```python
from .testing import InMemoryRouter
__all__ = [..., "InMemoryRouter"]
```

Пример использования в unit-тесте:
```python
from multiprocess_framework.modules.state_store_module import (
    InMemoryRouter,
    StateStoreManager,
    StateProxy,
    TreeStore,
)

def test_proxy_set_get():
    router = InMemoryRouter()
    store = TreeStore()
    manager = StateStoreManager(
        process_name="ProcessManager",
        store=store,
        router=router,
    )
    manager.initialize()

    proxy = StateProxy(
        process_name="camera_0",
        router=router,
        server_target="ProcessManager",
    )
    router.register_message_handler("state.changed", proxy.on_state_changed)

    proxy.set("cameras.0.fps", 30)
    assert proxy.get("cameras.0.fps") == 30
```

**Прецедент:** `unittest.mock`, `pytest`, `django.test` — все фреймворки предоставляют testing-helpers как часть публичного API.

**Последствия:**
- DRY: нет копирования MockBus в каждый тест
- Ясность: разработчик сразу видит, как писать тесты
- Собственность: testing helpers в одном месте, легко обновлять
- Интеграция: InMemoryRouter встроен в фреймворк, не требует доп. зависимостей

**Связанные решения:** ADR-SS-001 (InMemoryRouter реализует IRouter Protocol)

---

## Индекс ADR

| ID | Название | Статус | Фаза |
|----|-----------|---------|----|
| ADR-SS-001 | IRouter Protocol | ✅ Готово | 2.1 |
| ADR-SS-002 | server_target параметр | ✅ Готово (TODO Фаза 4) | 2.1 |
| ADR-SS-003 | migration_fn callback | ✅ Готово | 2.1 |
| ADR-SS-004 | Публичные хелперы паттернов | ✅ Готово | 2.1 |
| ADR-SS-005 | GuiStateProxy ленивый импорт | ✅ Готово | 2.1 |
| ADR-SS-006 | Авто-регистрация state.changed | ⏸️ TODO | 4 |
| ADR-SS-007 | exclude_self логика | ✅ Готово | 2.1 |
| ADR-SS-008 | Адресная доставка | ✅ Готово | 2.1 |
| ADR-SS-009 | ABC vs Protocol | ✅ Готово | 2.1 |
| ADR-SS-010 | InMemoryRouter testing | ✅ Готово | 2.1 |

