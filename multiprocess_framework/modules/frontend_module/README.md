# frontend_module — UI-фреймворк

## Назначение

Модуль-конструктор для сборки GUI из переиспользуемых компонентов.
Новый проект может поднять интерфейс за 30 минут: регистры + хуки + виджеты.

**Конкретные классы регистров** (поля, `FieldMeta`) задаёт приложение — фреймворк их не поставляет.

## Quick-start: подключение к процессу

### 1. Определить хуки запуска

```python
from frontend_module import FrontendLaunchHooks, run_process_attached_frontend

hooks = FrontendLaunchHooks(
    build_ui_config=lambda proc: {"title": "My App"},
    build_registers=lambda: (registers_manager, connection_map),
    create_command_sender=lambda proc: RoutedCommandSender(proc, targets),
    register_windows=my_register_windows,
    on_registers_boot=None,  # опционально
)
```

### 2. Запустить UI

```python
exit_code = run_process_attached_frontend(
    process_ref,
    hooks=hooks,
    initial_window="loading",
    loading_delay_ms=2000,
)
```

Последовательность внутри: `build_ui_config → build_registers → create_command_sender → on_registers_boot → FrontendManager.initialize → register_windows → run_app`.

### 3. Зарегистрировать окна

```python
def my_register_windows(wm, fm, config, sender, app, process_ref):
    wm.register("loading", lambda: LoadingWindow(parent=None))
    wm.register("main", lambda: create_main_window(fm, config, sender))
```

## Создание MainWindow

Типичное главное окно: `HeaderWidget` (шапка) + `ImagePanelWidget` (камеры) + `TabWidget` (вкладки настроек).

```python
from frontend_module.widgets import HeaderWidget, TabWidget, ImagePanelWidget

header = HeaderWidget(config=header_config)
tabs = TabWidget()
tabs.add_tab("processing", ProcessingTab(rm=rm, callbacks=cbs))
image_panel = ImagePanelWidget()
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
from frontend_module.widgets import BaseWidget

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

## Привязка к регистрам (RegisterBindingContext)

`RegisterBindingContext` — проверяет наличие `RegistersManager` и переключает виджет между NumericControl (с привязкой) и fallback QLineEdit (без привязки).

```python
from frontend_module.widgets.tabs import RegisterBindingContext

ctx = RegisterBindingContext(rm=registers_manager)
if ctx.can_bind:
    control = NumericControl.create(
        registers_manager=ctx.rm,
        binding=BindingConfig(register_name=REG, field_name="min_area"),
    )
else:
    control = QLineEdit()  # fallback без регистров
```

## Структура модуля

```
frontend_module/
├── __init__.py              # Публичный API
├── interfaces.py            # IRegistersManagerGui, ISignalProvider, ...
├── application/             # FrontendManager, WindowManager, ThreadManager
│   └── process_attached_frontend.py  # run_process_attached_frontend + FrontendLaunchHooks
├── core/                    # qt_imports, WidgetRegistry, WindowRegistry, FrontendRegistersBridge
├── components/              # Контролы: slider, checkbox, spinbox, numeric, compound, group, label
│   ├── base/                # Протоколы (IControlView, INumericView), трейты, инфраструктура
│   ├── examples/            # Учебные адаптеры и схемы (используются тестами)
│   └── ...
├── widgets/                 # Высокоуровневые виджеты: BaseWidget, HeaderWidget, TabWidget, ImagePanelWidget
│   ├── base_widget/         # BaseWidget[TModel] — MVP-паттерн
│   ├── header/              # HeaderWidget, HeaderConfig
│   ├── tabs/                # TabWidget, TabPresenterBase, RegisterBindingContext, MvpTabBase
│   ├── windows/             # LoadingWindow, MainWindow
│   └── tables/              # StructuredTableWidget, TreeWithToolbar
├── debug/                   # UiEventTap + команды ui.tap.* — UI-события (кнопки/табы) агентам через backend_ctl
├── schemas/                 # WidgetDescriptor, WindowConfig, RegisterBinding
├── configs/                 # FrontendManagerConfig, WindowManagerConfig
├── styling/                 # Стили, тема
└── tests/
```

## Зависимости

- **Зависит от:** `data_schema_module`, `config_module`, `registers_module`
- **Используется в:** `multiprocess_prototype` (GuiProcess), `multiprocess_prototype`

## Реально используемый публичный API

Из top-level `__init__.py` прототипами импортируются:

| Символ | old prototype | v3 |
|--------|:---:|:---:|
| `FrontendLaunchHooks` | + | + |
| `run_process_attached_frontend` | + | + |
| `FrontendManager` | + (тесты) | — |

Остальные символы (BaseWidget, TabWidget, HeaderWidget и т.д.) импортируются из подпакетов напрямую:
`frontend_module.widgets`, `frontend_module.components`, `frontend_module.core`.

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

```python
from multiprocess_framework.modules.frontend_module.tabs import TabRegistry, TabSpec

TABS = [TabSpec(id="settings", title="Settings", view_permission="tabs.settings.view",
                factory=make_settings)]
registry = TabRegistry(
    TABS,
    factory_context=(app_services, runtime),   # opaque, форвардится фабрике
    access_source=auth_state,                    # AccessContextSource
    placeholder_factory=make_placeholder,        # заглушка для вкладок без factory
)
registry.create_tabs(window.tab_widget)
```

Публичный API реэкспортирован в `interfaces.py`.
