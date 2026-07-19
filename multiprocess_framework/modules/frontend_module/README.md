# frontend_module — UI-фреймворк

## Назначение

Модуль-конструктор для сборки GUI из переиспользуемых компонентов.
Новый проект может поднять интерфейс за 30 минут: регистры + вкладки + виджеты.

**Конкретные классы регистров** (поля, `FieldMeta`) задаёт приложение — фреймворк их не поставляет.

> **Два поколения (frontend-constructor Ф1, 2026-07-18):** этот README описывает
> **Gen-2** — живой генерик-конструктор, который реально использует прототип v3
> (`TabSpec`/`TabRegistry`, MVP-базы, компоненты-контролы, `TelemetryViewModel`,
> `AppIdentity`). Первое поколение (`FrontendManager`/`WindowManager`/
> `run_process_attached_frontend` и реестры вокруг них) не используется v3 —
> см. раздел **«Legacy (Gen-1)»** внизу и `STATUS.md` (полный инвентарь с
> grep-доказательствами).

## Quick-start: TabSpec + TabRegistry + MVP + формы + TelemetryViewModel

### 1. Описать вкладки декларативно (`TabSpec` + `TabRegistry`)

```python
from multiprocess_framework.modules.frontend_module import TabRegistry, TabSpec

TABS = [
    TabSpec(
        id="settings",
        title="Settings",
        view_permission="tabs.settings.view",
        factory=lambda ctx: SettingsTabWidget(rm=ctx.registers_manager),
    ),
]

registry = TabRegistry(
    TABS,
    factory_context=app_services,        # opaque, форвардится фабрике как ctx
    access_source=auth_state,             # AccessContextSource
    placeholder_factory=make_placeholder, # заглушка для вкладок без прав
)
registry.create_tabs(window.tab_widget)
```

### 2. MVP-вкладка (`MvpTabBase` + `TabPresenterBase`)

Tab shell — тонкий контейнер на `MvpTabBase` (композиция дочерних виджетов,
пустой `_connect_signals` по умолчанию — связи вешаются в презентере):

```python
from multiprocess_framework.modules.frontend_module.widgets.tabs import (
    MvpTabBase,
    RegisterBindingContext,
    TabPresenterBase,
    create_registers_placeholder,
)

class SettingsTabWidget(MvpTabBase):
    def _init_ui(self):
        layout = QVBoxLayout(self)
        binding = RegisterBindingContext(rm=self._registers_manager)
        if not binding.can_bind:
            layout.addWidget(create_registers_placeholder("Settings"))
            layout.addStretch()
            return
        # ... строить форму (см. шаг 3), подключить к self._presenter

    def _create_presenter(self, model):
        return SettingsTabPresenter(view=self, rm=self._registers_manager)


class SettingsTabPresenter(TabPresenterBase["SettingsTabView", None]):
    def on_threshold_changed(self, value: int) -> None:
        self._view.show_status(f"threshold={value}")
```

Полный шаблон (tab shell vs фиче-виджет, callbacks.py, view.py) —
`widgets/tabs/MVP_TEMPLATE.md`, `widgets/tabs/TAB_STRUCTURE.md`.

### 3. Форма: контролы, привязанные к регистрам (`components`)

```python
from multiprocess_framework.modules.frontend_module.components import (
    BindingConfig,
    NumericControl,
    SliderControl,
)

if binding.can_bind:
    control = SliderControl.create(
        registers_manager=binding.rm,
        binding=BindingConfig(register_name="draw", field_name="threshold"),
    )
else:
    control = QLineEdit()  # fallback без регистров
```

### 4. Телеметрия: read-model поверх потока дельт (`TelemetryViewModel`)

```python
from multiprocess_framework.modules.frontend_module import TelemetryViewModel

vm = TelemetryViewModel()  # приложение наполняет своим потоком дельт (bridge → on_state_delta)
vm.on_state_delta({"data_type": "state_delta", "path": "processes.camera.fps", "value": 29.7})
value = vm.get("processes.camera.fps")            # текущее значение — локально, без похода на сервер
snapshot = vm.snapshot("processes.camera")        # снимок поддерева по префиксу
history = vm.history("processes.camera.fps")      # кольцевой буфер (для путей из tracked_suffixes), по запросу
```

## Создание своего виджета (BaseWidget pattern)

`BaseWidget[TModel]` — MVP-виджет с опциональной моделью и жизненным циклом:

1. `_coerce_callbacks(callbacks)` — нормализовать колбэки
2. `_coerce_ui(ui)` — нормализовать UI-конфиг
3. `_create_model()` → Model или None
4. `_init_ui()` — построить UI (без сигналов)
5. `_create_presenter(model)` → Presenter
6. `_connect_signals()` — связать UI и Presenter

```python
# Импортировать из подпакета напрямую (не из facade frontend_module.widgets —
# известная circular-import ловушка base_widget/tabs, см. docstring widgets/__init__.py).
from multiprocess_framework.modules.frontend_module.widgets.base_widget import BaseWidget

class MyWidget(BaseWidget[MyModel]):
    def _coerce_callbacks(self, cbs):
        return MyCbs() if cbs is None else cbs

    def _coerce_ui(self, ui):
        return MyUiConfig() if ui is None else ui

    def _create_model(self):
        return MyModel(self._registers_manager)

    def _init_ui(self):
        self._slider = SliderControl.create(
            registers_manager=self._registers_manager,
            binding=BindingConfig(register_name=REG, field_name="threshold"),
        )
        # ... layout

    def _create_presenter(self, model):
        return MyPresenter(view=self, model=model)

    def _connect_signals(self):
        self._slider.presenter.on_value_changed(self._presenter.on_threshold)
```

## Идентичность приложения (`AppIdentity`)

`frontend_module` — generic-фреймворк, не знает имя конкретного продукта.
Composition root инжектирует org/имя/лого **до** создания первого виджета,
читающего идентичность (`AppHeaderWidget`, `LoadingWindow`):

```python
from multiprocess_framework.modules.frontend_module import AppIdentity, set_app_identity

set_app_identity(AppIdentity(org="Acme", app_name="Acme App"))
```

## Структура модуля

```
frontend_module/
├── __init__.py               # Публичный API (Gen-2 — фасад-флип Ф1)
├── interfaces.py             # Protocol'ы контракта + реэкспорт tabs/state/app_identity
├── tabs/                     # NEW-D1: generic-механизм вкладок — TabSpec, TabRegistry, LazyTab
├── state/                    # FE-005: read-model телеметрии — TelemetryViewModel, TelemetryHistorySource
├── components/                # Контролы: slider, checkbox, spinbox, numeric, compound, group, label
│   ├── base/                  # Протоколы (IControlView, INumericView), трейты, инфраструктура
│   └── examples/               # Учебные адаптеры и схемы (используются тестами)
├── widgets/                    # Составной UI: BaseWidget, HeaderWidget, TabWidget, ImagePanelWidget
│   ├── base_widget/            # BaseWidget[TModel] — MVP-паттерн
│   ├── header/                  # HeaderWidget, HeaderConfig
│   ├── tabs/                    # TabWidget, TabPresenterBase, RegisterBindingContext, MvpTabBase, SectionSpec
│   └── tables/                  # StructuredTableWidget, TreeWithToolbar
├── managers/                    # ThemeManager, ConfigSnapshotManager, YamlPersistenceStore[T], AccessContext
├── debug/                       # UiEventTap + команды ui.tap.* — UI-события агентам через backend_ctl
├── core/                        # qt_imports, app_identity, app_context, diagnostics, ... (частично Legacy — см. STATUS.md)
├── application/                  # LEGACY Gen-1 (frozen) — FrontendManager, WindowManager, ThreadManager
├── schemas/                       # LEGACY Gen-1 (widget_descriptor/window_config) + живой register_binding
├── configs/                        # LEGACY Gen-1 (frozen) — FrontendManagerConfig, WindowManagerConfig
├── windows/                         # LEGACY Gen-1 (frozen) — LoadingWindow
└── tests/
```

## Зависимости

- **Зависит от:** `data_schema_module`, `config_module`, `registers_module`
- **Используется в:** `multiprocess_prototype` (v3) — deep-импортами Gen-2
  подпакетов (`tabs`, `state`, `components`, `widgets.tabs`, `core.app_identity`),
  мимо top-level фасада (0 импортов `from frontend_module import ...` в
  прототипе на 2026-07-18)

## Публичный API фасада (`frontend_module/__init__.py`, Gen-2)

| Символ | Источник |
|--------|----------|
| `SupportsCommandMessage`, `IRouterLike`, `IRegistersManager`, `IRegistersManagerGui`, `IConfigurableWidget`, `IWidgetFactory`, `IWidgetRegistry`, `ISignalProvider`, `IWindowRegistry`, `IFrontendManager` | `interfaces.py` (протоколы контракта) |
| `TabSpec`, `TabRegistry`, `LazyTab`, `AccessContextSource`, `PlaceholderFactory` | `tabs/` (NEW-D1) |
| `TelemetryViewModel`, `TelemetryHistorySource`, `DEFAULT_TRACKED_SUFFIXES` | `state/` (FE-005) |
| `AppIdentity`, `get_app_identity`, `set_app_identity` | `core/app_identity.py` (NEW-2) |
| `components` | Фасад подпакета — примитивы контролов |
| `widgets` (в т.ч. `widgets.tabs`) | Фасад подпакета — составной UI, MVP-базы |

Остальные символы (`HeaderWidget`, `TabWidget`, `StructuredTableWidget` и т.д.)
доступны через `frontend_module.widgets`/`frontend_module.components` напрямую.
Исключение — `BaseWidget`/`WidgetSignalBus`: известная circular-import
ловушка (`base_widget` ⇄ `widgets.tabs`, задокументирована в docstring
`widgets/__init__.py`) не даёт им попасть в `widgets.__all__` при импорте
пакета «с нуля» — используйте прямой путь
`frontend_module.widgets.base_widget.BaseWidget` (см. пример выше).

## Механизм вкладок (`frontend_module.tabs`, NEW-D1)

Generic-реестр вкладок приложения (перенос из прототипа, ADR-135). Приложение
описывает вкладки декларативно и строит их реестром — механизм не знает
конкретных вкладок и не импортирует прикладной слой.

| Символ | Назначение |
|--------|-----------|
| `TabSpec` | Описание вкладки: `id`, `title`, `view_permission`, `factory`, `description`; порядок = позиция в списке |
| `TabRegistry` | Строит вкладки из `Sequence[TabSpec]`, лениво инстанцирует, фильтрует по правам, подписан на смену `AccessContext` |
| `LazyTab` | Обёртка ленивой инициализации (содержимое создаётся при первом показе) |
| `AccessContextSource` | Контракт источника прав (`access_context` + сигнал `access_context_changed`) |

Публичный API реэкспортирован в `interfaces.py` и `frontend_module/__init__.py`.

## Legacy (Gen-1)

Первое поколение конструктора — **не используется прототипом v3** (v1/v2
удалены, e128b930; инвентарь с grep-доказательствами — `STATUS.md`). Правило
владельца: freeze, не kill (Р4 `plans/frontend-constructor/plan.md`) — пакеты
остаются импортируемыми (докстринг-маркер `LEGACY Gen-1 (frozen 2026-07-18)`),
но исключены из публичного фасада. Тесты помечены pytest-маркером `legacy_gen1`.

### Подключение к процессу (историческое, Gen-1)

```python
from multiprocess_framework.modules.frontend_module.application import (
    FrontendLaunchHooks,
    run_process_attached_frontend,
)

hooks = FrontendLaunchHooks(
    build_ui_config=lambda proc: {"title": "My App"},
    build_registers=lambda: (registers_manager, connection_map),
    create_command_sender=lambda proc: RoutedCommandSender(proc, targets),
    register_windows=my_register_windows,
    on_registers_boot=None,  # опционально
)

exit_code = run_process_attached_frontend(
    process_ref,
    hooks=hooks,
    initial_window="loading",
    loading_delay_ms=2000,
)
```

Последовательность внутри: `build_ui_config → build_registers → create_command_sender → on_registers_boot → FrontendManager.initialize → register_windows → run_app`.

```python
def my_register_windows(wm, fm, config, sender, app, process_ref):
    wm.register("loading", lambda: LoadingWindow(parent=None))
    wm.register("main", lambda: create_main_window(fm, config, sender))
```

### Legacy-пакеты

| Пакет | Назначение | Статус |
|-------|-----------|--------|
| `application/` | `FrontendManager`, `WindowManager`, `ThreadManager`, `run_process_attached_frontend` | LEGACY, frozen |
| `core.widget_registry` | `WidgetRegistry` | LEGACY, frozen |
| `core.window_registry` | `WindowRegistry` | LEGACY, frozen |
| `core.default_factories` | `create_default_registry` | LEGACY, frozen |
| `core.layout_composer` | `compose_layout` | LEGACY, frozen |
| `schemas.widget_descriptor` | `WidgetDescriptor` | LEGACY, frozen |
| `schemas.window_config` | `WindowConfig` | LEGACY, frozen |
| `configs/` | `FrontendManagerConfig`, `WindowManagerConfig` | LEGACY, frozen |
| `windows/` | `LoadingWindow` | LEGACY, frozen |

Полный инвентарь с grep-доказательствами 0 внешних потребителей — `STATUS.md`.
