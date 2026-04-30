# Widget Cookbook — руководство по созданию виджетов

Справочник для разработчиков `frontend_module`. Описывает четыре уровня абстракции,
паттерны создания компонентов и виджетов, а также регистрацию вкладок.

---

## 1. Обзор уровней абстракции

| Уровень | Что это | Базовый класс | Когда использовать |
|---------|---------|---------------|---------------------|
| **Component** (form control) | Атомарный элемент формы (чекбокс, слайдер, числовое поле) | `IControlView[T]` + Presenter с traits | Нужен единичный контрол с привязкой к полю регистра |
| **Widget** (feature panel) | Функциональная панель, собранная из Components | `BaseWidget[TModel]` | Панель с бизнес-логикой, несколько контролов, модель данных |
| **Tab** (обёртка вкладки) | Тонкая обёртка для встраивания Widget в TabWidget | `PanelTabBase` или `BaseTab` | Нужна вкладка с placeholder при отсутствии RegistersManager |
| **Window** (окно) | Верхнеуровневый контейнер приложения | `QMainWindow` | Главное окно, окно загрузки, диалог |

**Путь данных:** Component привязан к одному полю регистра. Widget собирает несколько Component и добавляет бизнес-логику через Presenter. Tab оборачивает Widget, проверяя наличие RegistersManager. Window содержит TabWidget с набором Tab.

---

## 2. Как создать Component (form control)

### Структура папки

```
components/<name>/
├── __init__.py      # Реэкспорт публичного API
├── config.py        # Наследник BaseControlConfig — UI-настройки
├── view.py          # Qt-виджет, реализует IControlView[T]
├── presenter.py     # Бизнес-логика: traits (Schema, Sync, Access, Debounce)
├── facade.py        # Статический .create() — фабрика, возвращает Result(widget, presenter)
└── defaults.py      # (опционально) Преднастроенные варианты
```

### config.py

Наследник `BaseControlConfig` из `frontend_module.components.base.config`.
`BaseControlConfig` даёт поля `label`, `tooltip`, `enabled`, `access_level`.
Добавляйте специфичные поля контрола:

```python
from dataclasses import dataclass
from typing import Literal
from frontend_module.components.base.config import BaseControlConfig, LabelOverride

@dataclass
class MyControlViewConfig(BaseControlConfig):
    """UI-настройки контрола."""
    position: Literal["left", "right"] = "left"

    def to_label_override(self) -> LabelOverride:
        return LabelOverride(label=self.label)
```

### view.py

Qt-виджет, реализующий контракт `IControlView[T]` из `frontend_module.components.base.interfaces`.
Обязательные методы:

- `setup(label, tooltip, enabled)` — начальная настройка
- `set_value(value)` / `set_value_silent(value)` — установка значения (с/без эмита сигнала)
- `get_value()` — текущее значение
- `set_enabled(enabled)` — переключение интерактивности
- `on_changed(callback)` — подписка на изменение пользователем
- `on_finished(callback)` — подписка на завершение ввода (для debounce)
- `show_error(message)` — отображение ошибки

### presenter.py

Композиция traits — без наследования, через инъекцию:

```python
from frontend_module.components.base.traits import SchemaTrait, SyncTrait, AccessTrait

class MyControlPresenter:
    def __init__(self, binding, adapter, view_config=None, current_access_level=0, hooks=None):
        self._schema = SchemaTrait(binding, adapter, config_override)
        self._sync = SyncTrait(binding, adapter)
        self._access = AccessTrait(self._schema.effective_access_level)
        self._view = None

    def attach_view(self, view):
        """Подключить view, настроить подписи, подписаться на изменения."""
        ...
```

Доступные traits:

| Trait | Назначение |
|-------|-----------|
| `SchemaTrait` | Метаданные из регистра (label, tooltip, min/max) |
| `SyncTrait` | Чтение/запись значения в регистр, подписка на внешние изменения |
| `AccessTrait` | Проверка уровня доступа (`can_modify()`) |
| `DebounceTrait` | Задержка записи (для числовых полей с клавиатуры) |

### facade.py

Статическая фабрика — единственный публичный способ создать контрол:

```python
from dataclasses import dataclass
from frontend_module.components.base import RegisterAdapter
from frontend_module.core.qt_imports import QWidget

@dataclass
class MyControlResult:
    widget: QWidget
    presenter: MyControlPresenter

class MyControl:
    @staticmethod
    def create(registers_manager, binding, view_config=None, ...) -> MyControlResult:
        adapter = RegisterAdapter(registers_manager)
        presenter = MyControlPresenter(binding, adapter, view_config, ...)
        view = MyControlView(...)
        presenter.attach_view(view)
        return MyControlResult(widget=view, presenter=presenter)
```

### Каноничный пример

`components/checkbox/` — полный рабочий компонент с config, view, presenter, facade, defaults.

---

## 3. Как создать Widget (feature panel)

### Структура папки

```
widgets/<name>/
├── __init__.py        # Реэкспорт: Widget, UiConfig, Callbacks
├── schemas.py         # Pydantic-схема UiConfig (SchemaBase) или dataclass
├── model.py           # Доступ к данным (регистры, менеджеры)
├── presenter.py       # Бизнес-логика UI
└── panel_widget.py    # BaseWidget[TModel] с lifecycle
```

### schemas.py

UI-конфигурация. Если используется `coerce_schema_config` — наследовать `SchemaBase` (Pydantic).
Для простых случаев — обычный `dataclass`:

```python
from data_schema_module import SchemaBase

class MyPanelUiConfig(SchemaBase):
    """UI-конфигурация панели."""
    touch_keyboard: dict | None = None
    show_advanced: bool = False
```

### model.py

Слой данных. Инкапсулирует обращения к регистрам и внешним менеджерам.
Не содержит Qt-код:

```python
@dataclass
class MyPanelModel:
    """Модель данных панели."""
    registers_manager: Any = None
    # ... бизнес-поля
```

### presenter.py

Бизнес-логика UI. Получает model и view, управляет состоянием:

```python
class MyPanelPresenter:
    def __init__(self, model, view):
        self._model = model
        self._view = view

    def on_activated(self):
        """Вызывается после полной инициализации UI."""
        pass
```

### panel_widget.py — lifecycle BaseWidget

`BaseWidget[TModel]` определяет жизненный цикл инициализации.
Порядок вызовов в `__init__`:

```
1. _coerce_callbacks(callbacks)  — нормализация колбэков
2. _coerce_ui(ui)                — нормализация UI-конфига (dict → UiConfig)
3. _create_model()               — создание Model (или None)
4. _init_ui()                    — построение UI (layouts, виджеты)
5. _create_presenter(model)      — создание Presenter
6. _connect_signals()            — привязка сигналов UI к Presenter
7. _on_presenter_ready(**kwargs) — пост-инициализация (опционально)
```

Пример реализации:

```python
from frontend_module.widgets.base_widget import BaseWidget
from frontend_module.core.qt_imports import QVBoxLayout, QLabel

class MyPanelWidget(BaseWidget[MyPanelModel]):

    def _coerce_ui(self, ui):
        # dict → UiConfig, None → дефолтный
        from frontend_module.core.schema_config import coerce_schema_config
        return coerce_schema_config(ui, MyPanelUiConfig)

    def _create_model(self):
        return MyPanelModel(registers_manager=self._registers_manager)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        # ... добавляем виджеты, Components
        layout.addWidget(QLabel("Моя панель"))

    def _create_presenter(self, model):
        return MyPanelPresenter(model=model, view=self)

    def _connect_signals(self):
        # Привязка Qt-сигналов к методам presenter
        pass
```

### signal_bus — внешние события

`BaseWidget` предоставляет `signal_bus` (`WidgetSignalBus`) для уведомления внешних подписчиков:

```python
# Внутри виджета:
self.emit_widget_event("settings_changed", {"key": "value"})

# Снаружи:
widget.signal_bus.event_emitted.connect(my_handler)
```

### Каноничные примеры в прототипе

`multiprocess_prototype/frontend/widgets/hikvision_widget` — полный MVP-виджет с BaseWidget.
`multiprocess_prototype/frontend/widgets/camera_common` — SimWebcam-виджет.

---

## 4. Как создать Tab wrapper

### Вариант A: PanelTabBase (простые вкладки)

Для вкладок, которые просто оборачивают один Widget с проверкой RegistersManager.
Задаются **3 атрибута класса** — и всё:

```python
from frontend_module.widgets.tabs import PanelTabBase

class ProcessingTab(PanelTabBase[ProcessingPanelWidget, ProcessingUiConfig]):
    _panel_class = ProcessingPanelWidget
    _config_class = ProcessingUiConfig
    _placeholder_name = "Обработка"
```

`PanelTabBase` автоматически:
- Нормализует `ui` через `coerce_schema_config`
- Проверяет `RegisterBindingContext.can_bind`
- Показывает placeholder, если `RegistersManager` отсутствует
- Создаёт панель (`_panel_class`) с проброшенными параметрами

Для дополнительных kwargs панели переопределить `_build_panel_kwargs() -> dict`.

### Вариант B: BaseTab (сложные вкладки)

Для вкладок с кастомной логикой (combo + stack, несколько вложенных виджетов, свой презентер):

```python
from frontend_module.widgets.tabs import BaseTab

class CameraTab(BaseTab):
    def __init__(self, *, registers_manager=None, ui=None, parent=None, **kwargs):
        super().__init__(parent)
        # Своя логика: combo, QStackedWidget, несколько виджетов
        ...

    def on_tab_selected(self):
        """Хук: вкладка стала активной."""
        ...

    def on_tab_deselected(self):
        """Хук: вкладка перестала быть активной."""
        ...
```

### Когда что выбрать

| Критерий | PanelTabBase | BaseTab |
|----------|-------------|---------|
| Один Widget внутри | Да | Избыточно |
| Нужен placeholder | Автоматически | Руками |
| Combo + Stack | Нет | Да |
| Свой презентер вкладки | Нет | Да |
| Несколько виджетов | Нет | Да |

---

## 5. Как зарегистрировать виджет

### Регистрация вкладки в TabWidget

Вкладки добавляются через фабрику в конфигурации приложения.
Типичный паттерн:

```python
from frontend_module.widgets.tabs import TabWidget

# Создание TabWidget
tab_widget = TabWidget(parent=window)

# Добавление вкладок
camera_tab = CameraTab(registers_manager=rm, ui=camera_ui)
processing_tab = ProcessingTab(registers_manager=rm, ui=proc_ui)

tab_widget.addTab(camera_tab, "Камера")
tab_widget.addTab(processing_tab, "Обработка")
```

### Реэкспорт в __init__.py

Каждый модуль вкладки/виджета экспортирует публичный API:

```python
# widgets/my_panel/__init__.py
from .panel_widget import MyPanelWidget
from .schemas import MyPanelUiConfig

__all__ = ["MyPanelWidget", "MyPanelUiConfig"]
```

### Окна (Window)

Окна размещаются в `frontend_module/windows/` и создаются приложением напрямую.
Текущие окна: `LoadingWindow`. Главное окно создаётся в launcher-слое прототипа.

---

## Быстрый старт

1. Скопировать `widgets/_template/` в `widgets/<my_name>/`
2. Переименовать классы `Template*` → `MyFeature*`
3. Заполнить `schemas.py` полями UI-конфига
4. Заполнить `model.py` полями данных
5. Реализовать `_init_ui()` в `panel_widget.py` — создать layout и компоненты
6. Реализовать `presenter.py` — бизнес-логику
7. Подключить сигналы в `_connect_signals()`
8. При необходимости создать Tab-обёртку через `PanelTabBase` (3 строки)
