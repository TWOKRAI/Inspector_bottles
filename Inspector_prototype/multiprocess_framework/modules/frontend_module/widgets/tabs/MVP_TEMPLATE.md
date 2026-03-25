# Шаблон MVP-вкладки и фиче-виджета

См. **Tab shell vs фиче-виджет** в `TAB_STRUCTURE.md`.

- **Tab shell** — тонкий контейнер (`BaseTab`): скролл, placeholder, композиция. Эталон: `multiprocess_prototype/frontend/widgets/tabs_setting/camera_tab`.
- **Фиче-виджет** — переиспользуемый блок на **`BaseWidget`**. Эталон: `multiprocess_prototype/frontend/widgets/hikvision_widget`.

## BaseWidget vs MvpTabBase

| Вариант | Когда | Где вешать связи UI → логика |
|---------|--------|------------------------------|
| **`BaseWidget`** | Фиче-виджет, нужна явная карта сигналов | Переопределить `_connect_signals()` (как HikvisionWidget) |
| **`MvpTabBase`** | Наследник `BaseWidget` с пустым `_connect_signals` по умолчанию | В `__init__` презентера или `_on_presenter_ready` |

Оба проходят один жизненный цикл `BaseWidget` (см. `../base_widget/README.md`).

## Структура папки фиче-виджета (`BaseWidget`)

```
feature_widget/
├── __init__.py
├── widget.py       # subclass BaseWidget[M] — _init_ui, _connect_signals, View methods
├── presenter.py
├── view.py         # Protocol: методы обновления UI для презентера
├── callbacks.py    # опционально: frozen dataclass
├── model.py        # опционально; иначе презентер + rm
└── schemas.py      # UiConfig
```

## Структура папки tab shell (MVP презентер вкладки)

```
feature_tab/
├── __init__.py
├── widget.py       # BaseTab или MvpTabBase — композиция дочерних виджетов
├── presenter.py    # опционально (как camera_tab)
├── view.py
├── callbacks.py
├── schemas.py
└── ui_coerce.py   # опционально
```

## widget.py tab shell (наследует MvpTabBase)

```python
from frontend_module.widgets.tabs import MvpTabBase, RegisterBindingContext, callback_no_args
from frontend_module.core.schema_config import coerce_schema_config

class FeatureTabWidget(MvpTabBase):
    def _coerce_callbacks(self, callbacks):
        if isinstance(callbacks, dict):
            return FeatureTabCallbacks.from_dict(callbacks)
        return callbacks or FeatureTabCallbacks()

    def _coerce_ui(self, ui):
        return coerce_schema_config(ui, FeatureTabUiConfig)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        binding = RegisterBindingContext(rm=self._registers_manager)
        if not binding.can_bind:
            from frontend_module.widgets.tabs import create_registers_placeholder
            layout.addWidget(create_registers_placeholder("Feature"))
            layout.addStretch()
            return
        # ... строить UI, подключить к self._presenter.on_xxx

    def _create_presenter(self, model):
        return FeatureTabPresenter(view=self, callbacks=self._callbacks, rm=..., ui=self._ui)

    def _on_presenter_ready(self, **kwargs):
        # опционально: sync initial state
        pass

    # View Protocol
    def set_some_value(self, value: str) -> None: ...
    def get_user_input(self) -> str: ...
```

## callbacks.py (frozen dataclass + tab_callbacks_from_dict/to_dict)

```python
from dataclasses import dataclass
from frontend_module.widgets.tabs import tab_callbacks_from_dict, tab_callbacks_to_dict

_FIELD_NAMES = ("on_action", "on_other",)

@dataclass(frozen=True)
class FeatureTabCallbacks:
    on_action: Optional[Callable[[], None]] = None
    on_other: Optional[Callable[[int], None]] = None

    def to_dict(self):
        return tab_callbacks_to_dict(self, _FIELD_NAMES)

    @classmethod
    def from_dict(cls, d: dict) -> "FeatureTabCallbacks":
        return tab_callbacks_from_dict(cls, d, _FIELD_NAMES)
```

## presenter.py (TabPresenterBase)

```python
class FeatureTabPresenter(TabPresenterBase["FeatureTabView", "FeatureTabUiConfig"]):
    def __init__(self, *, view, callbacks, rm, ui):
        super().__init__(view=view, rm=rm, ui=ui)
        self._callbacks = callbacks

    def on_action_clicked(self) -> None:
        if self._callbacks.on_action:
            self._callbacks.on_action()
        self._view.set_some_value("done")
```

## view.py (TabViewProtocol + Protocol)

```python
class FeatureTabView(TabViewProtocol, Protocol):
    def set_some_value(self, value: str) -> None: ...
    def get_user_input(self) -> str: ...
```
