# Структура вкладки — шаблон и рекомендации

Документ описывает рекомендованный подход к созданию вкладок приложения: когда использовать MVP, как организовывать файлы, какие утилиты применять. Эталонная реализация — `multiprocess_prototype/frontend/widgets/tabs_setting/camera_tab`.

**Фреймворк:** `MvpTabBase` (фасад), `create_registers_placeholder`, `tab_callbacks_from_dict`/`to_dict`, шаблон — `MVP_TEMPLATE.md`.

---

## Выбор подхода: MVP vs простой виджет

| Критерий | MVP (View + Presenter) | Простой виджет |
|----------|------------------------|----------------|
| Сложная логика | Да | Нет |
| Колбэки в backend (команды) | Да | Нет |
| Регистры + привязка | Да | Возможно |
| Секции с bind/fallback | Да | Редко |
| Примеры | camera_tab | settings_tab, processing_tab, recipes_tab — простой виджет + `RegisterBindingContext` |

**Когда использовать MVP:**
- Вкладка отправляет команды в процессы (start/stop, enum devices, set parameters)
- Несколько источников данных (регистр + внешние обновления)
- Секции с `RegisterBindingContext` (NumericControl при rm / fallback при отсутствии)

**Когда достаточно простого виджета:**
- Только контролы `frontend_module.components` по конфигу, без колбэков
- Все контролы уже привязаны к регистрам

---

## Рекомендуемая структура папки вкладки (MVP)

```
feature_tab/
├── __init__.py           # Публичный API: Widget, UiConfig, Callbacks
├── widget.py             # Виджет, реализует View Protocol, делегирует в Presenter
├── presenter.py          # Логика без Qt: регистр, колбэки, вызов методов View
├── view.py               # Protocol с методами, которыми Presenter управляет UI
├── callbacks.py          # frozen dataclass с Optional[Callable] полями
├── schemas.py            # UiConfig (SchemaBase), default_tab_item()
├── ui_coerce.py          # coerce_schema_config(ui, UiConfig) — тонкая обёртка
├── register_ops.py       # Работа с IRegistersManagerGui без виджетов (опционально)
├── section_a.py          # Секции UI (используют RegisterBindingContext)
├── section_b.py
└── pages/                # Подстраницы (опционально)
    ├── __init__.py
    └── page_a.py
```

---

## Паттерн Callbacks dataclass

Колбэки — типизированный frozen dataclass вместо словаря. Фреймворк не навязывает поля; каждая вкладка определяет свои.

```python
from dataclasses import dataclass
from typing import Callable, Optional

@dataclass(frozen=True)
class FeatureTabCallbacks:
    """Колбэки отправки команд в backend."""

    on_start: Optional[Callable[[], None]] = None
    on_stop: Optional[Callable[[], None]] = None
    # ... остальные поля

    def to_dict(self) -> dict[str, Optional[Callable]]:
        """Для совместимости с кодом, ожидающим словарь."""
        return {"on_start": self.on_start, "on_stop": self.on_stop, ...}

    @classmethod
    def from_dict(cls, d: dict) -> "FeatureTabCallbacks":
        """Собрать из словаря (launcher, legacy)."""
        return cls(**{k: d.get(k) for k in ("on_start", "on_stop", ...)})
```

См. `camera_tab/callbacks.py` — эталон.

---

## create_registers_placeholder

Для вкладок без RegistersManager — единая заглушка без дублирования текста и стилей:

```python
from frontend_module.components.tabs import create_registers_placeholder

if not binding.can_bind:
    layout.addWidget(create_registers_placeholder("Обработка"))
    layout.addStretch()
    return
```

---

## RegisterBindingContext в секциях

Секции (fps_section, hikvision_params и т.п.) принимают `RegisterBindingContext` вместо сырого `Optional[IRegistersManagerGui]`:

```python
def add_section_to_layout(
    layout,
    *,
    binding: RegisterBindingContext,
    ui: FeatureTabUiConfig,
    on_slider_changed: Callable[[int], None],
) -> SectionRefs:
    if binding.can_bind and binding.rm is not None:
        result = NumericControl.create(binding.rm, BindingConfig(...))
        layout.addWidget(result.widget)
        return SectionRefs(None, None)
    # Fallback: QLabel + QSlider
    ...
```

Так убираются размазанные проверки `hasattr(rm, "set_field_value")`.

---

## coerce_schema_config для UI

Нормализация `None` / `dict` / экземпляр в валидный `UiConfig`:

```python
from frontend_module.core.schema_config import coerce_schema_config

def coerce_feature_ui(ui: Optional[Union[FeatureTabUiConfig, dict]]) -> FeatureTabUiConfig:
    return coerce_schema_config(ui, FeatureTabUiConfig)
```

Конструктор виджета: `self._u = coerce_feature_ui(ui)`.

---

## callback_no_args для Qt-сигналов

Qt `clicked(bool)` передаёт аргумент; колбэки вида `on_start: Callable[[], None]` его не ожидают.

```python
from frontend_module.components.tabs import callback_no_args

_btn = lambda f: callback_no_args(f)
button.clicked.connect(_btn(callbacks.on_start))
```

---

## View Protocol и Presenter

**View** — `typing.Protocol` с методами, которыми презентер обновляет UI. Виджет реализует этот протокол. Презентер не импортирует Qt.

**Presenter** — `__init__(self, *, view, callbacks, rm, ui)`. Порядок: обновить регистр → вызвать колбэк → при необходимости обновить вью.

Эталон: `camera_tab/view.py`, `camera_tab/presenter.py`.

### Каркас во фреймворке (`mvp_pattern.py`)

| Символ | Назначение |
|--------|------------|
| `TabViewProtocol` | Маркер: вью вкладки без Qt в презентере. Конкретный протокол наследует его: `class MyTabView(TabViewProtocol, Protocol): ...` |
| `TabPresenterBase` | Общие поля `_view`, `_rm`, `_ui`; подкласс вызывает `super().__init__(...)` и добавляет колбэки и обработчики |

Пример: `CameraTabPresenter(TabPresenterBase[CameraTabView, CameraTabUiConfig])`.

---

## Связь с другими документами

- **DECISIONS.md** (ADR-071, ADR-072, ADR-073 и др.) — протокол `IRegistersManagerGui`, паттерн вкладок, презентеры
- **multiprocess_prototype/docs/FRONTEND_MAP.md** — как лаунчер собирает контекст и фабрику вкладок в приложении
