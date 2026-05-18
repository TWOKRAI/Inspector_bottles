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

## Binding-aware mode (form_ctx)

Когда `CheckboxControl.create(..., form_ctx=form_ctx)` получает `FormContext` — все записи идут через
`ActionBus` с coalescing, undo/redo и IPC bridge (`TopologyBridge`). Это **обязательный** путь для
plugin-форм (PluginsTab, InspectorPanel, ServicesTab).

```mermaid
sequenceDiagram
    participant U as User
    participant V as CheckboxView
    participant P as CheckboxPresenter
    participant FC as FormContext
    participant AB as ActionBus
    participant H as FieldSetHandler
    participant RM as RegistersManager
    participant S as SyncTrait

    U->>V: клик
    V->>P: on_changed(bool)
    P->>FC: write(register, field, new, old)
    FC->>AB: execute(action)
    AB->>H: apply → rm.set_field_value
    H->>RM: set_field_value
    RM->>S: subscribe callback
    S->>P: _on_external_change
    P->>V: set_value_silent
```

Для **undo**: `bus.undo()` → `FieldSetHandler.revert` → тот же путь через subscribe-callback →
`set_value_silent` — view возвращается к старому значению без лишней перезаписи.

**Шаблон для тиражирования:** копируй `CheckboxControl.create(..., form_ctx=...)` при реализации
SpinBoxControl, SliderControl, NumericControl и других builders. Контракт `form_ctx` / `None` должен
соблюдаться во всех новых controls.

## Отличия от числового контроля

- Нет **DebounceTrait** и **ValueTransformer** — булево пишется сразу по `on_changed`.
- **on_finished** у view — намеренный no-op (см. `IControlView`).
- **LegacySync** не подключён; при необходимости мост к v1 добавляют в presenter по образцу `NumericPresenter`.

## Пример

```python
from frontend_module.components.base.config import BindingConfig
from frontend_module.components.checkbox import (
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

- `frontend_module/tests/test_checkbox_v2.py` — unit: presenter без Qt, smoke фасада.
- `frontend_module/tests/test_controls_v2_hooks.py` — колбэки on_write_committed / on_write_rejected.
- `frontend_module/tests/integration/test_form_context_integration.py` — integration:
  round-trip click→write→undo→rollback через реальный `ActionBus` (`test_checkbox_form_ctx_roundtrip`)
  и блокировка UI по `access_level` (`test_checkbox_disabled_when_user_level_below_access_level`).
