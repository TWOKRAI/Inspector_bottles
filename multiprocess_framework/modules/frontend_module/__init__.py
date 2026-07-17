"""
Frontend Module — модуль UI-фреймворка (конструктор PySide6-приложений).

## Основные подсистемы

**Приложение:**
- frontend_module.application — FrontendManager, WindowManager, ThreadManager

**Компоненты (primitives):**
- frontend_module.components — SliderControl, CheckboxControl, NumericControl, ...

**Виджеты:**
- frontend_module.widgets.entity_editor — EntityTreeWidget, ParamsForm, BaseEditorModel, ...
- frontend_module.widgets.chrome — AppHeaderWidget, RecordingIndicator, SearchFilterBar, ...
- frontend_module.widgets — BaseWidget, TabWidget, TableWidget, ...

**Action Bus (undo/redo):**
- Вынесен в отдельный модуль `multiprocess_framework.modules.actions_module`
  (Action, ActionBuilder, ActionBus, ActionHandler — carve-out 2026-05-11, ADR-124)

**Вкладки (generic-механизм, NEW-D1):**
- frontend_module.tabs — TabSpec, TabRegistry, LazyTab, AccessContextSource.
  Приложение описывает вкладки как `list[TabSpec]` в composition root; реестр
  строит/лениво инстанцирует/фильтрует по правам. 0 обратных импортов.

**Read-model телеметрии (generic):**
- frontend_module.state — TelemetryViewModel, TelemetryHistorySource,
  DEFAULT_TRACKED_SUFFIXES. Локальный read-model «запись — всегда, чтение —
  локально, история — по запросу»: приложение наполняет VM своим потоком дельт
  и читает снимок/историю без похода на сервер. 0 обратных импортов.

**Менеджеры:**
- frontend_module.managers — ThemeManager, ConfigSnapshotManager, YamlPersistenceStore[T],
  AccessContext, RecipeManagerProtocol, SettingsProfileManagerProtocol

**Ядро:**
- frontend_module.core — qt_imports, qt_thread_guard, app_context, diagnostics, ...
- frontend_module.schemas — WidgetDescriptor, WindowConfig, RegisterBinding
- frontend_module.configs — FrontendManagerConfig, WindowManagerConfig

## Правило границы

Этот модуль НЕ импортирует из прototипа. Доменные расширения — через наследование:

    from multiprocess_framework.modules.frontend_module.managers import ThemeManager
    class MyThemeManager(ThemeManager):
        def __init__(self): super().__init__(styles_dir=..., default_variables_provider=...)

    from multiprocess_framework.modules.actions_module import ActionBuilder
    class AppActionBuilder(ActionBuilder):
        @staticmethod
        def domain_action(...) -> Action: ...
"""

from multiprocess_framework.modules.frontend_module.application import (
    FrontendLaunchHooks,
    FrontendManager,
    RoutedCommandSender,
    WindowManager,
    run_process_attached_frontend,
)

__all__ = [
    "FrontendManager",
    "FrontendLaunchHooks",
    "RoutedCommandSender",
    "WindowManager",
    "run_process_attached_frontend",
]

__version__ = "0.4.0"  # Phase 2.2: actions, entity_editor, chrome, managers, core extensions
