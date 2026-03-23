# Checkbox v2

Чекбокс с привязкой к регистру: **View** (`CheckboxView`) + **Presenter** (`CheckboxPresenter`) + **Facade** (`CheckboxControl`).

Те же порты, что и в [`base/README.md`](../base/README.md): `IFieldBinding`, `IRegisterPort`, `RegistersManagerLike`. Опционально **`ControlHooks`** в `CheckboxControl.create(..., hooks=...)` — отклонённая/успешная запись в регистр.

## Слои

```mermaid
flowchart LR
    F[CheckboxControl.create]
    V[CheckboxView]
    P[CheckboxPresenter]
    T[SchemaTrait + SyncTrait + AccessTrait]
    A[RegisterAdapter]
    F --> V & P
    P --> V
    P --> T --> A
```

## Поток значения

```mermaid
sequenceDiagram
    participant U as User
    participant V as CheckboxView
    participant P as CheckboxPresenter
    participant S as SyncTrait
    participant R as RegisterAdapter
    U->>V: клик
    V->>P: on_changed(bool)
    P->>S: write(value)
    S->>R: write(...)
    R-->>P: subscribe callback
    P->>V: set_value_silent
```

## Отличия от числового контроля

- Нет **DebounceTrait** и **ValueTransformer** — булево пишется сразу по `on_changed`.
- **on_finished** у view — намеренный no-op (см. `IControlView`).
- **LegacySync** не подключён; при необходимости мост к v1 добавляют в presenter по образцу `NumericPresenter`.

## Пример

```python
from frontend_module.components.control_v2.base.config import BindingConfig
from frontend_module.components.control_v2.checkbox import (
    CheckboxControl,
    CheckboxViewConfig,
)

result = CheckboxControl.create(
    registers_manager,
    BindingConfig(register_name="renderer", field_name="show_mask"),
    CheckboxViewConfig(position="left"),
)
layout.addWidget(result.widget)
```

## Тесты

`frontend_module/tests/test_checkbox_v2.py`, `test_controls_v2_hooks.py` (колбэки записи).
