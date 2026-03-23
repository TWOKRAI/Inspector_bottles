# Шаблон MVP-вкладки

Копировать в `feature_tab/` и заполнить. Эталон: `camera_tab`.

## Структура папки

```
feature_tab/
├── __init__.py
├── widget.py
├── presenter.py
├── view.py
├── callbacks.py
├── schemas.py
└── ui_coerce.py   # опционально
```

## widget.py (наследует MvpTabBase)

```python
from frontend_module.components.tabs import MvpTabBase, RegisterBindingContext, callback_no_args
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
            from frontend_module.components.tabs import create_registers_placeholder
            layout.addWidget(create_registers_placeholder("Feature"))
            layout.addStretch()
            return
        # ... строить UI, подключить к self._presenter.on_xxx

    def _create_presenter(self):
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
from frontend_module.components.tabs import tab_callbacks_from_dict, tab_callbacks_to_dict

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
