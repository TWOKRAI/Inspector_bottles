# Phase E Migration Guide: presenter AppContext → AppServices

**Дата:** 2026-05-27
**Статус:** Актуально для Phase E (Pipeline → Processes → Recipes → Services → Plugins → Displays)
**Образец миграции:** [`multiprocess_prototype/frontend/widgets/tabs/settings/tab.py`](../../multiprocess_prototype/frontend/widgets/tabs/settings/tab.py) — Settings tab уже мигрирован в D.5.

---

## Контекст

Phase D создала инфраструктуру AppServices DI:

- `AppServices` dataclass (10 полей) — собирается в `app.py:run_gui()` через `build_app_services()`.
- `QtEventBus` — thread-safe обёртка, доступна как `services.events`.
- `ConfigStore` Protocol + adapter — `services.config`.
- Deprecation shim — `ctx.extras["X"]` эмитит `DeprecationWarning` с подсказкой «используй `ctx.app_services.Y`».
- Settings tab — proof-of-concept миграции (D.5), паттерн подтверждён Qt-MCP smoke.

**Phase E мигрирует** оставшиеся табы в порядке: **Pipeline → Processes → Recipes → Services → Plugins → Displays**. Settings уже сделан.

---

## До / После: сигнатура presenter'а

**До (Phase D и раньше):**

```python
class PipelineTab(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx
        # доступ через ctx.extras["X"] → deprecated с Phase D
        topology = self._ctx.extras["topology_holder"].get_topology()
        bus = self._ctx.action_bus()
```

**После (Phase E):**

```python
from multiprocess_prototype.domain.app_services import AppServices

class PipelineTab(QWidget):
    def __init__(self, services: AppServices, *, parent: QWidget | None = None) -> None:
        self._services = services
        # прямой доступ через services.X
        topology = self._services.topology.load()
```

**Адаптер для TabFactory** (до полного удаления AppContext в Phase F):

```python
@classmethod
def create(cls, ctx: AppContext) -> "PipelineTab":
    assert ctx.app_services is not None, (
        "AppServices не инициализирован. Task D.1 должен быть выполнен в run_gui()."
    )
    return cls(ctx.app_services)
```

---

## Маппинг extras → AppServices

Полная таблица замен из `_DEPRECATED_KEYS_MAP` в
`multiprocess_prototype/frontend/_deprecated_extras.py`:

| `ctx.extras[key]` | `services.X` | Типичная операция |
|---|---|---|
| `"plugin_registry"` / `"plugin_manager"` | `services.plugins` | `services.plugins.list()`, `services.plugins.get(id)` |
| `"registers_manager"` | `services.registers` | `services.registers.get_schema(name)` |
| `"service_registry"` | `services.services` | `services.services.start("x")`, `.stop("x")`, `.get_lifecycle("x")` |
| `"display_registry"` | `services.displays` | `services.displays.list()`, `.get(id)` |
| `"topology_holder"` / `"topology_bridge"` | `services.topology` | `services.topology.load()`, `.save(topology)` |
| `"command_catalog"` / `"action_bus"` | `services.commands` | `services.commands.dispatch(SomeCommand(...))` |
| `"recipe_manager"` | `services.recipes` | `services.recipes.activate(id)`, `.list()`, `.get(id)` |
| `"auth_manager"` / `"auth_state"` / `"audit_storage"` | `services.auth` | `services.auth.has_permission("admin")`, `.current_user()` |
| *(конфиг)* | `services.config` | `services.config.get("key")`, `.set("key", val)`, `.get_section("ui")` |

Ключи, которые **не** в этом маппинге (`bindings`, `tab_factory`, `service_state_adapter`),
остаются в `ctx.extras` тихо — они не покрыты AppServices Protocol'ами.

---

## Замена action bus

**До:**

```python
from multiprocess_framework.modules.frontend_module.action_bus import ActionBus

class FooPresenter:
    def __init__(self, ctx: AppContext) -> None:
        self._bus: ActionBus = ctx.action_bus()

    def on_save(self, data: dict) -> None:
        self._bus.execute(SaveSettingsAction(data=data))
```

**После:**

```python
from multiprocess_prototype.domain.commands import SaveSettingsCommand
from multiprocess_prototype.domain.app_services import AppServices

class FooPresenter:
    def __init__(self, services: AppServices) -> None:
        self._services = services

    def on_save(self, data: dict) -> None:
        self._services.commands.dispatch(SaveSettingsCommand(data=data))
```

Domain команды — **frozen dataclass** (immutable after creation). `dispatch()` возвращает обновлённый `Project` через внутренний цикл `Project.apply(command, ctx)`. Presenter получает изменение через EventBus-подписку, не через return value.

---

## Подписка на EventBus

```python
from multiprocess_prototype.domain.events import ProcessAdded, ProcessRemoved
from multiprocess_prototype.domain.protocols import Subscription

class PipelinePresenter:
    def __init__(self, services: AppServices) -> None:
        self._services = services
        self._subscriptions: list[Subscription] = []

    def setup(self) -> None:
        self._subscriptions.append(
            self._services.events.subscribe(ProcessAdded, self._on_process_added)
        )
        self._subscriptions.append(
            self._services.events.subscribe(ProcessRemoved, self._on_process_removed)
        )

    def _on_process_added(self, event: ProcessAdded) -> None:
        # вызывается на main thread (QtEventBus гарантирует маршалинг через QueuedConnection)
        self._refresh_view()

    def teardown(self) -> None:
        for sub in self._subscriptions:
            sub.unsubscribe()
        self._subscriptions.clear()
```

**В виджете — в `closeEvent`:**

```python
def closeEvent(self, event: QCloseEvent) -> None:
    self._presenter.teardown()
    super().closeEvent(event)
```

`QtEventBus` маршалит `publish()` из worker thread на main thread через
внутренний `Signal(object)` с `Qt.QueuedConnection` (Qt event loop). Подписчики
**всегда** получают события на main thread — Qt-виджеты обновлять безопасно.

---

## Тесты: builder вместо MagicMock

**Запрещено (Phase D+):**

```python
# НЕЛЬЗЯ — не даёт реальной проверки контракта
ctx = MagicMock(spec=AppContext)
ctx.extras = {"topology_holder": MagicMock()}
```

**Обязательно — builder `make_test_app_services()`:**

```python
from multiprocess_prototype.domain.tests._fakes import (
    make_test_app_services,
    FakePluginCatalog,
    FakeConfigStore,
)

def test_pipeline_shows_processes():
    plugins = FakePluginCatalog(plugins=[...])
    config = FakeConfigStore(data={"pipeline.mode": "live"})
    services = make_test_app_services(plugins=plugins, config=config)

    tab = PipelineTab(services)
    # assertions...
```

`make_test_app_services()` — функция-builder из `domain/tests/_fakes.py`. Все поля
имеют разумные fake-реализации по умолчанию. Переопределяй только то, что нужно тесту.

**Smoke-тест для pytest-qt:**

```python
def test_pipeline_tab_creates_without_error(qtbot):
    services = make_test_app_services()
    tab = PipelineTab(services)
    qtbot.addWidget(tab)
    assert tab.isVisible() or True  # smoke: не упал при создании
```

---

## Отладка DeprecationWarning

Чтобы увидеть, какие места ещё используют `ctx.extras` (для Phase E приоритизации),
запусти тесты с включёнными warnings:

```bash
python -m pytest multiprocess_prototype/ -W always::DeprecationWarning 2>&1 | grep "deprecated"
```

`pytest.ini` по умолчанию фильтрует warnings из `_deprecated_extras` (decision Q5 Phase D).
Явный `-W always` их раскрывает. Это полный список того, что Phase E должна мигрировать.

---

## Edge cases

### Фича не покрыта Protocol'ами

Если presenter использует метод, которого нет ни в одном из 9-ти Protocol'ов AppServices —
**оставь `ctx.extras` с явным комментарием**:

```python
# TODO Phase E: расширить Protocol X методом foo()
# ProcessesPresenter использует ctx.extras["topology_holder"].get_raw_dict() —
# TopologyRepository Protocol не покрывает raw-dict доступ.
raw = ctx.extras["topology_holder"].get_raw_dict()
```

Это сигнал для Phase E расширить соответствующий Protocol. Не изобретай workaround'ы.

### History / timeline логирование

`SettingsHistoryPresenter` и аналогичные компоненты могут напрямую использовать
`LoggerManager` для чтения логов. Это **вне scope Phase D/E** — отдельный aggregate
Phase G. Не трогай, не deprecate.

### AuthContext vs AuthFacade

`SettingsTab` получает `auth_ctx: AuthContext | None` отдельным параметром — потому что
`AuthFacade` Protocol в domain покрывает только `has_permission` / `current_user`.
Admin-панели используют полный `AuthContext` (manager + state + audit). Phase E расширит
`AuthFacade` Protocol или введёт `AdminAuthContext` Protocol. **Пока — оставляй `auth_ctx`
отдельным параметром**, как в Settings tab.

### bindings (GuiStateBindings)

`ctx.bindings()` — Qt-signal runtime state (live data bindings). **Не входит в AppServices**
(закрытый Q4 Phase D). 25+ точек использования в presenter'ах продолжают работать через
`AppContext.bindings`. Ревизия возможна в Phase G.

---

## Что Phase D НЕ покрыла (out of scope)

| Что | Когда |
|---|---|
| Удаление `ctx.extras` dict-bag | Phase F |
| Удаление 4 dataclass-обёрток (`TopologyContext`, `StateContext`, `PluginsContext`, `ActionsContext`) | Phase F |
| Live runtime snapshot (PID, FPS, метрики процессов) | Phase E/G (отдельный aggregate) |
| `bindings` (GuiStateBindings) перевод в AppServices | Phase G (возможная ревизия) |
| `error::DeprecationWarning` в тестах (force-fail) | Phase F |
| Расширение AuthFacade Protocol до Admin-уровня | Phase E (при миграции Processes/Admin tab) |

---

## Phase E follow-ups (из ревью Phase D)

Эти замечания **не блокируют** Phase D merge, но Phase E developer должен учесть:

1. **Split ConfigStore instance** — `build_app_services()` оборачивает `Config(initial_data=dict(ctx.config))`,
   что создаёт **отдельный** `Config` instance, не связанный с `ctx.config` не-мигрированных
   presenter'ов. Изменения через `services.config.set()` не видны через `ctx.config` и наоборот.
   В Phase D OK (только Settings мигрирован, и он использует yaml_io, не ctx.config), но Phase E
   при миграции нескольких табов должна решить: либо ConfigStoreFromManager wraps тот же backend
   что `ctx.config`, либо явно документировать split.

2. **ConfigStore subscriber recursion** — `set()` держит lock во время `_fire_subscribers()`.
   RLock + `list(self._subscribers)` копия защищают от мутации, но если handler A.set() триггерит
   handler B.set() → handler A.set() → ... это бесконечная рекурсия. В Phase D не проблема
   (Settings не делает reactive chains). Phase E добавит `_firing: bool` guard или `_depth_limit`.

3. **InterfaceSection ctx=None graceful degradation** — кнопка "Обновить UI" в Interface subtab'е
   получает `ctx=None` и логирует warning. Документированное ограничение Phase D; полноценная
   миграция требует расширения какого-то Protocol (например, `ProcessControlProtocol`) для
   GUI restart-фичи.

---

## Ссылки

- Образец миграции: `multiprocess_prototype/frontend/widgets/tabs/settings/tab.py`
- Маппинг deprecated ключей: `multiprocess_prototype/frontend/_deprecated_extras.py`
- AppServices dataclass: `multiprocess_prototype/domain/app_services.py`
- Fake-builder: `multiprocess_prototype/domain/tests/_fakes.py`
- Phase D план: `plans/2026-05-27_cross-tab-architecture/phase-d-app-services.md`
- Brief (target-архитектура): `docs/refactors/2026-05_cross_tab_architecture.md`
