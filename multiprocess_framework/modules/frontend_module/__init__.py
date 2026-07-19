"""
Frontend Module — модуль UI-фреймворка (конструктор PySide6-приложений).

## Публичный фасад (Gen-2, живое поколение)

Фасад-флип (frontend-constructor Ф1, T1.2): `__all__` этого модуля отдаёт
только живое поколение — контракт см. также в `interfaces.py`.

**Контракт (Protocol'ы):**
- `SupportsCommandMessage`, `IRouterLike`, `IRegistersManager`,
  `IRegistersManagerGui`, `IConfigurableWidget`, `IWidgetFactory`,
  `IWidgetRegistry`, `ISignalProvider`, `IWindowRegistry`, `IFrontendManager`

**Вкладки (generic-механизм, NEW-D1):**
- `TabSpec`, `TabRegistry`, `LazyTab`, `AccessContextSource`, `PlaceholderFactory`.
  Приложение описывает вкладки как `list[TabSpec]` в composition root; реестр
  строит/лениво инстанцирует/фильтрует по правам. 0 обратных импортов.

**Read-model телеметрии (generic, FE-005):**
- `TelemetryViewModel`, `TelemetryHistorySource`, `DEFAULT_TRACKED_SUFFIXES`.
  Локальный read-model «запись — всегда, чтение — локально, история — по
  запросу»: приложение наполняет VM своим потоком дельт и читает снимок/историю
  без похода на сервер. 0 обратных импортов.

**Идентичность приложения (NEW-2, de-brand):**
- `AppIdentity`, `get_app_identity`, `set_app_identity`. Composition root
  инжектирует org/имя/лого ДО создания первого виджета, читающего идентичность.

**Компоненты и составной UI (фасады подпакетов):**
- `frontend_module.components` — примитивы контролов: SliderControl,
  CheckboxControl, NumericControl, ...
- `frontend_module.widgets` (в т.ч. `widgets.tabs`) — составной UI: BaseWidget,
  TabWidget, MVP-базы (MvpTabBase, TabPresenterBase, SectionSpec), HeaderWidget, ...

Остальные живые подсистемы, не входящие в top-level `__all__` (импортируются
из своих подпакетов напрямую):

- `frontend_module.managers` — ThemeManager, ConfigSnapshotManager,
  YamlPersistenceStore[T], AccessContext, RecipeManagerProtocol,
  SettingsProfileManagerProtocol
- `frontend_module.core` — qt_imports, qt_thread_guard, app_context,
  diagnostics, app_identity, ... (частично живое, частично Legacy — см. ниже)
- `frontend_module.debug` — UiEventTap + команды `ui.tap.*`
- `frontend_module.schema_adapter` — SchemaBase/FieldMeta адаптер; живая
  внутренняя зависимость (используется и Gen-2 виджетами `widgets.header`/
  `widgets.chrome`, и Legacy Gen-1)
- `frontend_module.schemas.register_binding` — `RegisterBinding`,
  `RegisterFieldMeta`, `ResolvedMeta`; живая зависимость `components.base.*`

**Action Bus (undo/redo):**
- Вынесен в отдельный модуль `multiprocess_framework.modules.actions_module`
  (Action, ActionBuilder, ActionBus, ActionHandler — carve-out 2026-05-11, ADR-124)

## LEGACY Gen-1 (frozen 2026-07-18)

Первое поколение конструктора (`FrontendManager`/`WindowManager`/
`run_process_attached_frontend` + вспомогательные реестры/схемы/конфиги) не
используется прототипом v3 (0 внешних потребителей — v1/v2 удалены, инвентарь
см. `STATUS.md`). Правило владельца: freeze, не kill (Р4 плана
`plans/frontend-constructor/plan.md`) — пакеты остаются импортируемыми,
но убраны из публичного фасада:

- `frontend_module.application` — `FrontendManager`, `WindowManager`,
  `ThreadManager`, `run_process_attached_frontend`, `FrontendLaunchHooks`
- `frontend_module.core.widget_registry` — `WidgetRegistry`
- `frontend_module.core.window_registry` — `WindowRegistry`
- `frontend_module.core.default_factories` — `create_default_registry`
- `frontend_module.core.layout_composer` — `compose_layout`
- `frontend_module.schemas.widget_descriptor` — `WidgetDescriptor`
- `frontend_module.schemas.window_config` — `WindowConfig`
- `frontend_module.configs` — `FrontendManagerConfig`, `WindowManagerConfig`,
  `FrontendThreadManagerConfig`
- `frontend_module.windows.loading_window` — `LoadingWindow` (Legacy-обвязка;
  сам класс интегрирован с живым `core.app_identity` — см. тест
  `test_app_identity.py::TestLoadingWindowUsesIdentity`)

Тесты этого поколения помечены pytest-маркером `legacy_gen1`.

## Правило границы

Этот модуль НЕ импортирует из прототипа. Доменные расширения — через наследование:

    from multiprocess_framework.modules.frontend_module.managers import ThemeManager
    class MyThemeManager(ThemeManager):
        def __init__(self): super().__init__(styles_dir=..., default_variables_provider=...)

    from multiprocess_framework.modules.actions_module import ActionBuilder
    class AppActionBuilder(ActionBuilder):
        @staticmethod
        def domain_action(...) -> Action: ...
"""

from multiprocess_framework.modules.frontend_module import components, widgets
from multiprocess_framework.modules.frontend_module.interfaces import (
    AccessContextSource,
    AppIdentity,
    DEFAULT_TRACKED_SUFFIXES,
    IConfigurableWidget,
    IFrontendManager,
    IRegistersManager,
    IRegistersManagerGui,
    IRouterLike,
    ISignalProvider,
    IWidgetFactory,
    IWidgetRegistry,
    IWindowRegistry,
    LazyTab,
    PlaceholderFactory,
    SupportsCommandMessage,
    TabRegistry,
    TabSpec,
    TelemetryHistorySource,
    TelemetryViewModel,
    get_app_identity,
    set_app_identity,
)

__all__ = [
    # Протоколы контракта модуля (реэкспорт из interfaces.py).
    "SupportsCommandMessage",
    "IRouterLike",
    "IRegistersManager",
    "IRegistersManagerGui",
    "IConfigurableWidget",
    "IWidgetFactory",
    "IWidgetRegistry",
    "ISignalProvider",
    "IWindowRegistry",
    "IFrontendManager",
    # Механизм вкладок (NEW-D1).
    "TabSpec",
    "TabRegistry",
    "LazyTab",
    "AccessContextSource",
    "PlaceholderFactory",
    # GUI read-model телеметрии (FE-005).
    "TelemetryViewModel",
    "TelemetryHistorySource",
    "DEFAULT_TRACKED_SUFFIXES",
    # Идентичность приложения (NEW-2).
    "AppIdentity",
    "get_app_identity",
    "set_app_identity",
    # Фасады подпакетов (составной UI).
    "components",
    "widgets",
]

__version__ = "0.5.0"  # Ф1 T1.2: фасад-флип — экспорт живого поколения (Gen-2), Gen-1 frozen
