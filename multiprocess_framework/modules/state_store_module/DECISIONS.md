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

## ADR-SS-006: Авто-регистрация handler-а state.changed в ProcessModule

**Контекст:** В Фазе 2.1 каждый рабочий процесс явно регистрирует handler для входящих дельт:

```python
router.register_message_handler("state.changed", proxy.on_state_changed)
```

Это требует от разработчика помнить о регистрации и добавлять строку в каждый процесс.

**Решение:**
- `ProcessModule.__init__` принимает `state_proxy: IStateProxy | None = None`
- Метод `_init_state_proxy()` вызывается в конце `initialize()` (после `_lifecycle.initialize()`)
- Если `state_proxy` задан и `router_manager` доступен — handler регистрируется автоматически
- Разработчик создаёт proxy в `_init_application_threads()` и назначает `self.state_proxy = proxy`

```python
# В конкретном процессе:
def _init_application_threads(self):
    self._state_proxy = StateProxy("name", router=self.router_manager, ...)
    self.state_proxy = self._state_proxy  # авто-регистрация в _init_state_proxy()
```

**Статус:** Реализовано (2026-05-08, T1.2).
Мигрированы все процессы прототипа: robot, camera, renderer, gui, database, processor.

**Последствия:** Упрощение интеграции для разработчика, прозрачность управления подписками. Новые процессы не могут «забыть» зарегистрировать handler.

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

## ADR-SS-011: PersistenceManager — конфигурируемые file_mapping и предикаты

**Дата:** 2026-05-07
**Контекст:** Изначально `PersistenceManager` содержал зашитую константу `_PREFIX_TO_FILE` с доменными ветвями (`cameras`/`renderer`/`robot`/`database`/`system`) и доменные предикаты (`_is_state_only` для `*.state.*`, `_is_system` для `system.*`). Это противоречило ADR-SS-003 (фреймворк не знает о доменных схемах) — `RecipeEngine` исправили callbacks-ами, а `PersistenceManager` остался зашитым.

**Решение:** Вынести три параметра в конструктор:

```python
PersistenceManager(
    store: TreeStore,
    data_dir: Path,
    debounce_seconds: float = 2.0,
    file_mapping: dict[str, str] | None = None,
    skip_predicate: Callable[[str], bool] | None = None,
    immediate_predicate: Callable[[str], bool] | None = None,
)
```

- `file_mapping`: маппинг `{prefix: filename}`. По умолчанию пустой → менеджер не сохраняет ничего.
- `skip_predicate`: какие пути пропускать (например, `*.state.*`). По умолчанию — ничего не пропускать.
- `immediate_predicate`: какие пути требуют save без debounce (например, `system.*`). По умолчанию — все пути идут через debounce.

Старые модульные функции `_resolve_file`, `_is_state_only`, `_is_system`, `_file_to_prefix`, словарь `_PREFIX_TO_FILE` удалены. Тесты модуля передают конкретный маппинг через фикстуру (фактически демонстрируя пример прикладной конфигурации).

**Последствия:**
- Фреймворк больше не знает доменных ветвей.
- Прикладной код несёт прямую ответственность за маппинг (что и должно быть).
- Защита от случайного срабатывания: без `file_mapping` менеджер полностью no-op.
- Это **breaking change** для прикладного кода: если приложение раньше полагалось на дефолтный маппинг, теперь нужно передавать его явно. На момент рефакторинга активный прототип `PersistenceManager` напрямую не подключал — миграция не требуется.

**Связанные решения:** ADR-SS-003 (RecipeEngine миграции), ADR-SS-009 (доменно-нейтральные публичные классы).

---

## ADR-SS-012: StateProxy — фильтрация callbacks по pattern на клиенте

**Дата:** 2026-05-07
**Контекст:** Сервер группирует дельты по `subscriber` через `DeltaDispatcher.dispatch()` и шлёт каждому подписчику ОДНО IPC-сообщение `state.changed` со списком всех дельт, попавших в его подписки. Если процесс держит несколько подписок (`cameras.0.*` и `renderer.*`), пакет содержит дельты обеих веток.

В прежней реализации `StateProxy._invoke_callbacks` вызывал каждый зарегистрированный callback **со всеми дельтами пакета**, не сопоставляя их с pattern конкретной подписки. Это создавало неявный контракт «callback должен сам разбираться, что его, а что чужое» — нигде не задокументированный и провоцирующий ошибки.

**Решение:** Хранить на клиенте маппинг `sub_id → pattern` (`StateProxy._sub_patterns`) и в `_invoke_callbacks` для каждого callback оставлять только дельты, чьи `delta.path` матчат `pattern` его подписки. Используется тот же `match_pattern`/`split_pattern`, что и на сервере — поведение клиента и сервера согласовано.

```python
def _invoke_callbacks(self, deltas: list[Delta]) -> None:
    for sub_id, cbs in list(self._callbacks.items()):
        pattern = self._sub_patterns.get(sub_id)
        if pattern is None:
            matched = deltas        # legacy / locally-only — без фильтрации
        else:
            matched = self._filter_deltas_by_pattern(deltas, pattern)
            if not matched:
                continue
        for cb in cbs:
            cb(matched)
```

Альтернатива (расширение проводного формата `state.changed` полем `sub_ids` per-delta) отвергнута: текущий подход не меняет IPC-формат, не требует миграции существующих клиентов и сохраняет дедупликацию по subscriber на сервере.

**Последствия:**
- Каждый callback видит только дельты, которые он реально просил → понятный, явный контракт.
- Внешний API `subscribe()/unsubscribe()` не изменился.
- IPC-формат `state.changed` не изменился.
- Накладные расходы: один проход matching на клиенте на пакет (для типичных 1-3 подписок и нескольких дельт — пренебрежимо).
- Legacy-режим: callback, добавленный напрямую в `_callbacks` без `subscribe()` (например, в тестах), получает дельты без фильтрации (pattern не сохранён).

**Связанные решения:** ADR-SS-007 (exclude_self), ADR-SS-008 (адресная доставка).

---

## ADR-SS-013: SubscriptionManager — публичные snapshot-методы для shutdown / DevTools

**Дата:** 2026-05-07
**Контекст:** `StateStoreManager.shutdown()` собирал имена подписчиков через прямой доступ `self._subs._lock` / `self._subs._by_subscriber.keys()`, а `StateInspector.subscriptions()` читал `self._sub_manager._subscriptions` — оба клиента лезли к приватным атрибутам менеджера. Это нарушало инкапсуляцию: рефактор внутреннего хранения сразу сломал бы обоих клиентов.

**Решение:** Добавить два публичных потокобезопасных метода в `SubscriptionManager`:

```python
def subscribers(self) -> list[str]: ...
def all_subscriptions(self) -> list[Subscription]: ...
```

`subscribers()` возвращает имена процессов, у которых есть хотя бы одна подписка. `all_subscriptions()` отдаёт снимок всех `Subscription` (frozen dataclass — безопасно отдавать наружу). Обе операции выполняются под `self._lock` и возвращают независимые списки.

`StateStoreManager.shutdown()` и `StateInspector.subscriptions()` переписаны на эти методы — приватных обращений к менеджеру в модуле больше нет.

**Последствия:**
- Внутреннее хранение (`_subscriptions: dict[str, Subscription]`, `_by_subscriber: dict[str, set[str]]`) можно менять без правок клиентов.
- DevTools и shutdown — публичные сценарии, явно отражённые в API.
- Snapshot — копия, поэтому даже модификация результата извне не влияет на состояние менеджера.

**Связанные решения:** ADR-SS-009 (ABC и публичные классы — следствие того же принципа инкапсуляции).

---

## ADR-SS-014: Монотонная revision дерева — отдельный счётчик, НЕ переиспользование fencing-epoch

**Дата:** 2026-07-11
**Контекст:** Задача Ф4.9 (etcd-паттерн: revision + watch-from-revision + resync) требует монотонного счётчика мутаций дерева. Ревью 2026-07-11 предложило переиспользовать epoch-счётчик fencing-механизма (`message_module/fencing/`, ADR-MSG-009) вместо нового третьего счётчика — там прямо зарезервирована формулировка «epoch остаётся в штампе для диагностики/Ф4.9».

**Анализ семантики — почему резерв ADR-MSG-009 НЕ подходит:**

| | `epoch` (ADR-MSG-009/ADR-PMM-010) | `revision` (Ф4.9, здесь) |
|---|---|---|
| Что считает | Поколение топологии процесса (incarnation-adjacent) | Мутация дерева состояния |
| Когда растёт | Редко: switch/restart процесса с пересозданием очередей | Часто: КАЖДЫЙ `set`/`merge`-лист/`delete`/`restore` |
| Область | **Per-sender** (в PSR, свой у каждого процесса) | **Per-tree** (один глобальный счётчик StateStoreManager) |
| Назначение | Fencing: отличить старый (заменённый) инстанс отправителя от текущего | Consistency: подписчик обнаруживает пропущенное `state.changed` |
| Уже известная проблема | ADR-PMM-014: epoch-критерий **ложно дропал** легитимные сообщения ТЕКУЩИХ процессов в переходном окне (поэтому fencing переехал на per-sender `incarnation`, epoch остался только диагностикой) | — |

Три структурных несовпадения делают переиспользование technically некорректным, а не просто «не по вкусу»:
1. **Разная область.** `epoch` живёт в PSR **на процесс**-отправитель; у дерева состояния нет «своего» отправителя — мутации приходят от N разных процессов. Чтобы получить единый монотонный ряд для дерева, пришлось бы либо агрегировать epoch-и всех отправителей (не монотонно и не detectable как gap), либо завести отдельный tree-level epoch — что и есть новый счётчик под другим именем.
2. **Разная частота.** `epoch` — редкое, дискретное событие (topology switch). `revision` должна расти на **каждую** мутацию (десятки-сотни в секунду в живой системе). Наложение этих кадансов на один счётчик либо испортит грубую семантику fencing (epoch начнёт «шуметь» на каждый `set`), либо не даст нужной гранулярности revision (пропущенные дельты между двумя switch неотличимы).
3. **Уже задокументированная ненадёжность для СВОЕЙ задачи.** ADR-PMM-014 прямо показал, что даже для fencing epoch как единственный критерий давал ложные срабатывания (заменён per-sender incarnation). Строить НА НЕМ ещё и data-consistency механизм означало бы наследовать эту нестабильность в совершенно другой контур.

**Решение:** Завести отдельный монотонный счётчик `TreeStore._revision: int`, инкремент на каждую успешную мутацию (`set`/`delete`/`restore` — по разу; `merge` — по разу на изменившийся лист, т.к. внутри реализован через `set()`). Идемпотентные операции (значение не изменилось) revision не трогают.

```python
class TreeStore(IStateStore):
    def __init__(self, ...):
        self._revision = 0

    @property
    def revision(self) -> int:
        return self._revision

    def _next_revision(self) -> int:
        self._revision += 1
        return self._revision
```

`Delta.revision: int = 0` (default — обратная совместимость: код, создающий `Delta` напрямую, не обязан её задавать). `IStateStore.revision` — новый абстрактный property в контракте (аддитивно, единственный имплементатор — `TreeStore`).

**Последствия:**
- Никакой связи с fencing/`message_module` — модули остаются независимыми (state_store_module и так не импортирует message_module).
- `epoch` продолжает служить ТОЛЬКО диагностике/fencing (как и было решено в ADR-MSG-009/ADR-PMM-014), без нагрузки чужой задачи.
- Обратная совместимость: `Delta.to_dict()/from_dict()` — аддитивное поле, `from_dict` читает `d.get("revision", 0)` (fail-open для дельт от старых отправителей).

**Отвергнуто:** переиспользование `_fence.epoch` из `message_module/fencing/token.py` как источника revision — по причинам выше (разная область/частота/уже известная ненадёжность для собственной задачи).

**Связанные решения:** [ADR-MSG-009](../message_module/DECISIONS.md#adr-msg-009-fencing-token--штамп-конверта--дроп-билета-устаревшего-инстанса-fencing--ф42), [ADR-PMM-014](../process_manager_module/DECISIONS.md) — где epoch зарезервирован (и почему резерв не годится), ADR-SS-015 (watch-from-revision resync).

---

## ADR-SS-015: watch-from-revision + resync — envelope-level gap-detection через существующий канал `state.get_subtree`

**Дата:** 2026-07-11
**Контекст:** Ф4.9b требует, чтобы подписчик (`StateProxy`), обнаруживший разрыв revision (пропущенное `state.changed`), сам восстановил консистентность кэша. Два вопроса дизайна: (1) как детектить разрыв, (2) каким каналом запрашивать resync.

**Решение — детект разрыва на уровне конверта, не отдельных дельт:**

`DeltaDispatcher._send_state_changed` проставляет `data.revision = max(d.revision for d in deltas)` — это revision **конверта** (единицы доставки `state.changed`), не отдельной Delta. `StateProxy._check_and_handle_revision_gap` сравнивает revision НОВОГО конверта с `_last_revision + 1`:

```python
if envelope_revision == expected:
    self._last_revision = envelope_revision  # норма
else:
    self._resync(patterns)                   # разрыв → resync
```

Сравнение именно конвертов (а не первой/последней Delta внутри пакета) осознанно: конверт — атомарная единица доставки IPC, и именно ЕЁ потерю (или потерю предыдущей) нужно обнаруживать. Гонять состояние по отдельным Delta.revision внутри пакета не даёт дополнительной точности (пакет либо доставлен целиком, либо не доставлен вовсе — `send_async` не режет сообщение на части), но усложняет код.

**Решение — resync переиспользует существующий канал `state.get_subtree`, НЕ заводит новую IPC-команду:**

`handle_state_get_subtree` расширен аддитивно: помимо `data.path` (литеральный путь, старое поведение) принимает `data.paths` (список glob-паттернов — тот же формат, что в `state.subscribe`). При наличии `paths` сервер строит объединённый снимок через уже существующий `TreeStore.snapshot(paths=...)` вместо `TreeStore.get_subtree(path)`. Ответ везде получает поле `revision` (текущая revision дерева на момент ответа).

```python
def handle_state_get_subtree(self, msg: dict) -> dict:
    data = self._extract_data(msg)
    paths = data.get("paths")
    if paths:
        value = self._store.snapshot(paths=list(paths))
    else:
        value = self._store.get_subtree(data.get("path", ""))
    return {"status": "ok", "value": value, "revision": self._store.revision, ...}
```

`StateProxy._resync(patterns)` шлёт `state.get_subtree` с `data.paths = список активных подписок этого proxy` (из `self._sub_patterns`, накопленного `subscribe()`/`ensure_subscription()`, 5.9), получает снимок + revision, полностью замещает в кэше все пути, попадающие под `patterns` (включая исчезновение путей, удалённых на сервере), и обновляет `_last_revision`.

**Почему НЕ новая команда `state.resync`:** `register_message_handlers`/`register_commands` регистрируют фиксированный набор из 7 команд — оба существующих теста (`test_initialize_with_router`, `test_register_message_handlers`) жёстко проверяют `len(...) == 7`. Задача прямо требует «зелёный стьют без правок ожиданий» и «механизм запроса — по существующим каналам». Расширение `state.get_subtree` — семантически корректно (resync и get_subtree — оба «дай мне текущее состояние поддерева(ьев)», различие только в one-path vs many-glob-patterns) и не меняет число зарегистрированных команд.

**Известное ограничение — ложные resync под конкурентными несвязанными записями:** `revision` — счётчик **дерева**, не per-pattern. Если подписчик наблюдает `cameras.0.**`, а параллельно кто-то пишет в `renderer.*`, revision дерева всё равно растёт — следующий конверт подписчику придёт с revision, которая не равна `_last_revision + 1` (промежуточные revision «съедены» неотносящимися к его подписке мутациями), хотя реальной потери сообщения не было. Это вызовет resync, которого можно было избежать.

Осознанно принято: resync — идемпотентная, дешёвая операция (переиспользует уже существующий `TreeStore.snapshot`), ложное срабатывание стоит одного лишнего round-trip, но НЕ ломает корректность (кэш всё равно сойдётся с сервером). Точная per-pattern семантика (без ложных срабатываний) потребовала бы либо per-subscriber sequence-номеров на сервере (доп. состояние в `DeltaDispatcher`, привязка к subscriber, а не к revision дерева), либо compaction-протокола как в etcd (revision watermarks). Оставлено кандидатом на будущее при подтверждённой проблеме в проде (в духе ADR-SS-011 — не усложнять раньше времени).

**Что было отвергнуто:**
- **Per-delta gap-detection** (сравнивать `deltas[0].revision`/`deltas[-1].revision` вместо `envelope_revision`) — сложнее, не даёт точности (см. выше), и текущая реализация IPC-конверта уже атомарна на уровне сообщения.
- **Отдельная IPC-команда `state.resync`** — ломает пин `len(registered_handlers) == 7` в существующих тестах без необходимости; `state.get_subtree` с `paths` покрывает тот же сценарий.
- **Per-subscriber sequence-номера** (точный gap-detection без ложных срабатываний) — избыточная сложность для MVP; резерв на будущее, если ложные resync окажутся заметны в проде.

**Последствия:**
- `GuiStateProxy.on_state_changed` переиспользует тот же `_check_and_handle_revision_gap`/`_resync` (унаследовано из `StateProxy`) — GUI-путь получает watch-from-revision «бесплатно», без дублирования логики.
- Обратная совместимость: пакеты без `data.revision` (старые отправители/тесты, использующие `{"data": {"deltas": [...]}}` без revision) — fail-open, gap-проверка пропускается целиком, поведение идентично до-Ф4.9.
- Задача **4.10** (driver watch-from-revision — конец-в-конец проверка в `backend_ctl`) осознанно НЕ входит в объём Ф4.9 — ядро (сервер + `StateProxy`) реализовано и покрыто тестами (`tests/test_watch_from_revision.py`), driver-обвязка — отдельная задача.

**Связанные решения:** ADR-SS-014 (revision-счётчик), ADR-SS-002 (`server_target`), ADR-SS-012 (per-pattern фильтрация — та же карта `_sub_patterns` переиспользована для сборки `patterns` в `_resync`).

**Пересмотр 2026-07-11 (Fable-ревью, находки HIGH-1/HIGH-2/MED-3/MED-4):** модель непрерывности «envelope == last+1» опровергнута собственным диспетчером — `merge()` инкрементирует revision на каждый лист и шлёт диапазон одним конвертом; глобальный счётчик + фильтрованная доставка (узкие подписки, `exclude_self`) делают невидимые ревизии нормой, а не аномалией. Новая модель: (1) конверт несёт `first_revision`+`revision` — непрерывность проверяется по диапазону пакета; (2) **инвариант: дельты доставленного пакета ВСЕГДА применяются к кэшу и доходят до callbacks/delta_sink** — resync только подстраховка, никогда не замена; (3) stale-пакет (`envelope <= last`, в полёте во время предыдущего resync) — игнор без resync; (4) неудачный resync — fail-open (пакет уже применён, `_last_revision` двигается по конверту). Прежний тезис «ложные resync безопасны» уточнён: безопасны только при выполнении инварианта (2) — до пересмотра gap глотал callbacks пакета.

---

## ADR-SS-016: StateProxy._send_sync обязан звать router.request(), а не router.send()

**Дата:** 2026-07-11
**Контекст:** Ревью Ф4.9 (2026-07-11, находка PLAUSIBLE-6) поставило под сомнение, действительно ли `_send_sync()` (общий helper для `get()`, `get_subtree()`, `subscribe()` и `_resync()`) получает от `router.send(msg)` ОТВЕТ обработчика на другом конце, а не просто статус доставки в очередь. Подозрение подтвердилось трассировкой `RouterManager`:

- `RouterManager.send()` (`router_module/core/router_manager.py`) — `return self._do_send(...)`, который резолвит канал и вызывает `channel.send(processed)`. `QueueChannel.send()` (`router_module/channels/queue_channel.py`) кладёт сообщение в очередь и возвращает `{"status": "success", "channel": name}` — **чистый transport-ack**, не ответ обработчика.
- Настоящий request/response с ожиданием ответа — отдельный метод `RouterManager.request(message, timeout)`: регистрирует pending-слот по `correlation_id`, шлёт через `send()`, блокируется на `threading.Event` до прихода `type=="response"` (резолвится в `receive()` → `_resolve_pending`) или таймаута. Ответ обработчика приходит через `reply_to_request(request_msg, result)`, вызываемый `_dispatch_command` ПОСЛЕ выполнения `CommandManager.handle_command()` — то есть `result` в конверте `request()` — это ровно то, что вернул handler (`{"status": "ok", "value": ..., "revision": ...}` для `handle_state_get_subtree` и т.п.).
- `IRouter.Protocol.send()` в `interfaces.py` был документирован как «синхронная отправка **с ожиданием ответа**» — сам контракт описывал желаемое поведение `request()`, а не то, что реально делает `RouterManager.send()`. Расхождение документации и реализации маскировало баг.
- Все тестовые дублёры модуля (`InMemoryRouter`, `MockRouter` в `test_state_proxy.py`/`test_state_store_manager.py`, `_RelayRouter` в `test_watch_from_revision.py`) реализуют `send()` как **прямой** request-reply (вызывают handler синхронно и возвращают его результат) — то есть воспроизводят семантику `request()`, а не `send()`. Это маскировало баг во всём test suite: юнит-тесты были зелёными, а в проде (реальный `RouterManager` между процессами) `get()`/`get_subtree()`/`subscribe()`/`_resync()` получали бы `{"status": "success", "channel": ...}` вместо ответа сервера.

**Решение:** `_send_sync()` предпочитает `router.request(msg, timeout=_SYNC_REQUEST_TIMEOUT)`, если router его поддерживает (`getattr(router, "request", None)` — утиная типизация, без изменения `IRouter` Protocol, чтобы не ломать существующие дублёры), разворачивает `envelope["result"]` (конверт `request()`: `{"success": bool, "result": <ответ handler'а>}`). Если router **не** поддерживает `request()` (тестовые дублёры) — используется прежний путь `router.send(msg)` без изменений, обратная совместимость всего test suite сохранена без правки самих дублёров.

```python
request_fn = getattr(self._router, "request", None)
if callable(request_fn):
    envelope = request_fn(msg, timeout=self._SYNC_REQUEST_TIMEOUT)
    if not isinstance(envelope, dict) or envelope.get("success") is False:
        return None  # fail-open
    result = envelope.get("result")
    return result if isinstance(result, dict) else envelope
return self._router.send(msg)  # legacy-путь для тестовых дублёров
```

Fail-open (таймаут/ошибка транспорта/некорректный ответ) → `None`, ровно как и раньше при `router=None`; вызывающий код (`get`/`get_subtree`/`subscribe`/`_resync`) уже трактует `None` как «ответа нет» и не падает.

**Последствия:**
- `_resync()` (ядро watch-from-revision, Ф4.9b) начинает реально работать по РЕАЛЬНОМУ каналу в проде — раньше получала бы `{"status":"success","channel":...}`, `response.get("status") != "ok"` → resync тихо считался бы неудавшимся на КАЖДОМ разрыве (маскировано зелёными тестами с дублёрами-фейками).
- `get()`/`get_subtree()`/`subscribe()` — та же проблема пред-Ф4.9 закрыта тем же фиксом (общий `_send_sync`), хотя явно не были предметом ревью Ф4.9 — исправлены как побочный эффект общего helper'а, без отдельного изменения их собственной логики.
- Новые тесты (`TestSendSyncPrefersRequestOverSend`, `test_state_proxy.py`) используют дублёр `_RealisticRouter`, воспроизводящий РЕАЛЬНОЕ разделение `send()`/`request()` — закрывают класс ошибок, который старые дублёры маскировали.
- `IRouter` Protocol НЕ расширен методом `request()` — намеренно: добавление обязательного метода в `runtime_checkable Protocol` не ломает duck-typing вызовы (изменение не enforced через `isinstance`), но расширение контракта потребовало бы синхронной правки всех существующих тестовых дублёров без функциональной необходимости (`getattr`-детект уже покрывает оба случая).

**Отвергнуто:**
- **Требовать от всех тестовых дублёров реализовать `request()`** — избыточная переработка широкого test suite ради единообразия; `getattr`-детект решает совместимость без этого.
- **Расширить `IRouter` Protocol обязательным `request()`** — Protocol используется только как type-hint (нет `isinstance(router, IRouter)` проверок в модуле), формальное расширение не даёт практической пользы, только увеличивает связанность контракта.

**Связанные решения:** ADR-SS-001 (IRouter Protocol), ADR-SS-015 (watch-from-revision resync — потребитель этого фикса).

---

## ADR-SS-017: `STATE_ENVELOPE_MARKER` — явный маркер конверта `state.merge`

**Дата:** 2026-07-13
**Контекст:** RS-ревью 2026-07-13 (`plans/2026-07-06_constructor-master/plan.md`, задача G.2) поставило под вопрос детекцию формы конверта `state.merge` в `handle_state_merge` (`manager/state_store_manager.py`). Прежде форма опознавалась **эвристикой (shape-sniffing)**: если у сообщения есть top-level `path`/`data` — считать его развёрнутым конвертом, иначе разворачивать `msg["data"]`. Эвристика была верифицирована корректной для обоих СУЩЕСТВУЮЩИХ путей вызова (через `RouterManager` full-message и через прямой вызов `expects_full_message=False`), но оставалась именно эвристикой: будущий отправитель, чей merge-**payload** случайно содержит top-level ключ `path` (например, мержит поддерево, где сам путь к узлу называется `path`), был бы принят за конверт и тихо замержен НЕ туда — payload ушёл бы в поля конверта, а не в дерево состояния.
**Решение:** Ввести явный ключ-маркер `STATE_ENVELOPE_MARKER = "_state_merge_envelope"` (`core/delta.py:24`) — вместо угадывания формы по составу полей. `StateProxy.merge()` (`proxy/state_proxy.py:135`) при формировании IPC-сообщения ставит маркер СИБЛИНГОМ рядом с `path`/`data`/`source` внутри конверта. `handle_state_merge` (`manager/state_store_manager.py:193`) читает маркер на двух уровнях:
- **Форма A (full message)** — маркер отсутствует на верхнем уровне `msg`; конверт вложен в `msg["data"]`, разворачивается один раз (`inner = msg.get("data")`).
- **Форма B (развёрнутый конверт)** — маркер `STATE_ENVELOPE_MARKER: True` стоит на верхнем уровне самого `msg` (путь `expects_full_message=False`, конверт передаётся как есть) → `msg` и есть конверт.

Дополнительно (F2 ревью G.2): `path` обязателен и должен быть непустой строкой — маркированный конверт с пустым/отсутствующим `path` **громко отклоняется** (`{"status": "error", ...}`), а не молча мержится в корень дерева (иначе пустой `path` затёр бы всё состояние).

```python
if msg.get(STATE_ENVELOPE_MARKER):
    envelope = msg                                   # (B) уже конверт
else:
    inner = msg.get("data")
    envelope = inner if isinstance(inner, dict) else msg   # (A) развернуть один раз
path = envelope.get("path", "")
if not path or not isinstance(path, str):
    return {"status": "error", "error": "Поле 'path' обязательно и должно быть строкой"}
```

**Последствия:**
- Класс бага «payload с top-level `path` тихо принят за конверт» закрыт структурно — детекция больше не зависит от состава пользовательских полей.
- IPC-формат `state.merge` не меняется для существующих отправителей (маркер — аддитивное поле внутри уже существующего конверта); тесты `test_state_store_manager.py` (маркированные и legacy-кейсы) — зелёные.
- Маркер — сосед transport-полей конверта (`_fence` из fencing-реестра Ф4.2, [ADR-MSG-009](../message_module/DECISIONS.md#adr-msg-009-fencing-token--штамп-конверта--дроп-билета-устаревшего-инстанса-fencing--ф42)): оба используют `_`-префиксный ключ как явный сигнал транспортного/конвертного назначения, а не доменных данных.
- Кандидат на дальнейшую формализацию: типизированный конверт (msgspec/Pydantic-схема команды `state.merge`) в рамках будущего инкремента G.9 контрактной плоскости ([ADR-COMM-006](../../DECISIONS.md), ось C) — маркер закрывает текущий риск, но не заменяет строгую схему.

**Связанные решения:** ADR-SS-008 (адресная доставка — тот же конверт `state.changed`/`state.merge`), [ADR-MSG-008](../message_module/DECISIONS.md#adr-msg-008-реестр-контрактов-сообщений-contracts--ф42) (реестр контрактов — сосед по мотивации «убрать угадывание формы сообщения»), [ADR-MSG-010](../message_module/DECISIONS.md#adr-msg-010-единый-конверт-команд--payload-под-data) (тот же Ф7 G.2, тот же класс проблемы — двойственность формы конверта — на стороне COMMAND).

---

## ADR-SS-018: ThrottleMiddleware — per-leaf троттл merge-поддерева + рантайм-мутабельность правил

**Контекст:** Троттл частоты обновлений задаётся правилами-глобами по листовым путям (`processes.**.state.fps: 1.0`) и до сих пор применялся только в `before_set`. Но телеметрия процессов публикуется через `proxy.merge` (self-publish в heartbeat, `process_heartbeat._publish_metrics_to_tree` → `build_worker_telemetry` → `proxy.merge`), а `ThrottleMiddleware.before_merge` не был переопределён — наследовал пропускающий дефолт базового класса. Итог: правила по листам де-факто НЕ действовали на телеметрию (rate-limit сводился только к периоду heartbeat, ~5 с глобально на процесс). «Частота per-параметр» была фикцией. Плюс правила фиксировались на старте (`orchestrator.use(ThrottleMiddleware(rules))`) — не было ни доступа к живому middleware по имени, ни мутатора для рантайм-управления (нужно для config hot-reload / backend_ctl, план `telemetry-publish-control`, Фаза 3).

**Решение (семантика merge — per-leaf):** `before_merge` разворачивает merge-поддерево (`path` = корень, `data` = вложенный dict) в листовые ПОЛНЫЕ пути (`path` + относительный путь листа) и применяет к каждому листу ту же логику правил, что `before_set`. Сопоставлять правила-глобы с КОРНЕМ merge (`processes.cam`) нельзя — они его не матчат, троттл остался бы no-op. Именно per-leaf делает правила `processes.**.state.fps` реально прореживающими телеметрийный merge.

- лист без правила → пропускается (консервативно: статусы/health/данные без явного правила не блокируются — инвариант «status/errors always»);
- правило `0` → лист вырезается навсегда (последнее значение копится в `_pending`);
- `interval > 0` → per-путь rate-limit по `_last_pass` (идемпотентно, последнее значение в `_pending`) — контракт идентичен `before_set`;
- ни один лист не покрыт правилом → merge проходит как есть (без копии); часть прошла/есть непокрытые → merge подрезается (придержанные листья вырезаны); все покрыты и все придержаны → merge отклонён целиком (`proceed=False`, симметрично `set`).

Дёшево и правильно: телеметрийные поддеревья малы (единицы воркеров × единицы метрик), обход листьев — копейки.

**Решение (рантайм-мутабельность):** `set_rules` / `update_rule(pattern, interval)` / `remove_rule(pattern)` меняют набор правил живьём; `MiddlewarePipeline.get(name)` + `StateStoreManager.get_middleware(name)` дают доступ к живому middleware по имени (для рантайм-команд). Потокобезопасность — **copy-on-write**: middleware читается из потока стора, а правила меняются из другого потока (рантайм-команды). Мутаторы под `Lock` строят НОВЫЙ dict и атомарно пере-присваивают `self._rules` (живой dict не правится на месте); путь чтения (`_find_rule`) берёт локальную ссылку и итерирует без блокировки — безопасно, т.к. пере-присваивание ссылки атомарно под GIL. `Lock` сериализует только мутатор-vs-мутатор. Тайминги при смене правил не сбрасываются: путь с изменённым интервалом переоценивается против нового интервала на следующем вызове (это и есть «живая» смена частоты); пути, потерявшие правило, дальше пропускаются (stale-тайминги безвредны).

**Последствия:**
- Правила теперь реально троттлят merge-телеметрию (разблокирует Фазы 1–3 плана); `before_set`-контракт не изменился (регресс покрыт).
- Тест `test_throttle.py` «before_merge всегда пропускает» переписан под новый контракт (per-leaf троттл, партиал-подрезка, отклонение).
- Read-path троттла без блокировки (COW) — нулевой overhead на hot-path стора.

**Связанные решения:** ADR-SS-017 (тот же конверт `state.merge`, чей payload теперь троттлится), план `telemetry-publish-control.md` (Task 0.1 — фундамент управляемой публикации).

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
| ADR-SS-011 | PersistenceManager — конфигурируемые маппинг и предикаты | ✅ Готово | 2.1+ |
| ADR-SS-012 | StateProxy — per-pattern фильтрация callbacks | ✅ Готово | 2.1+ |
| ADR-SS-013 | SubscriptionManager — публичные snapshot-методы | ✅ Готово | 2.1+ |
| ADR-SS-014 | revision дерева — отдельный счётчик, НЕ epoch fencing | ✅ Готово | 4.9 |
| ADR-SS-015 | watch-from-revision + resync через существующий state.get_subtree | ✅ Готово (пересмотрено 2026-07-11) | 4.9 |
| ADR-SS-016 | _send_sync — router.request(), не router.send() | ✅ Готово | 4.9 |
| ADR-SS-017 | STATE_ENVELOPE_MARKER — явный маркер конверта state.merge | ✅ Готово | Ф7 G.2 |
| ADR-SS-018 | ThrottleMiddleware — per-leaf троттл merge + рантайм-мутабельность правил | ✅ Готово | PC 0.1 |
