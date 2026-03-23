# example_with_data_schema

Учебный пакет: схемы `SchemaBase` (регистр + UI) и адаптеры ко всем основным фасадам v2: checkbox, slider, spinbox, составные контролы, отдельная подпись.

Содержит **только** схемы и сборку виджетов; без отдельного config-слоя приложения.

## Структура

```
example_with_data_schema/
├── adapter_common.py
├── checkbox/
├── slider/
├── spinbox/
├── compound_numeric/   # BGR: ExampleBgrTripletRegister + CompoundNumericControl
├── compound_mixed/     # bool + float: два класса регистра, один BINDING_REGISTER
└── label/              # только ExampleLabelUiConfig (без регистра)
```

- **schemas** — `BINDING_REGISTER` / `BINDING_FIELD` (кроме `label/`); поле регистра + UI-схема.
- **adapter** — `*_binding()`, `coerce_ui()`, `*_view_config_from_ui()`, `create_example_*()`.

## Примеры

### Checkbox / Slider / Spinbox

```python
from frontend_module.components.controls.example_with_data_schema import (
    create_example_checkbox,
    create_example_slider,
    create_example_spinbox,
)

create_example_checkbox(rm, ExampleCheckboxUiConfig(checkbox_label="Демо"))
create_example_slider(rm, ExampleSliderUiConfig(slider_label="Порог"))
create_example_spinbox(rm, ExampleSpinboxUiConfig(spinbox_label="Шаг"))
```

### Составной числовой (три канала, один `field` + `index`)

```python
from frontend_module.components.controls.example_with_data_schema.compound_numeric import (
    ExampleCompoundNumericUiConfig,
    create_example_compound_numeric,
)

r = create_example_compound_numeric(
    rm,
    ExampleCompoundNumericUiConfig(label_b="Blue", numeric_view_type="slider"),
)
layout.addWidget(r.widget)
```

### Смешанный (чекбокс + слайдер, `CompoundControl.items`)

```python
from frontend_module.components.controls.example_with_data_schema.compound_mixed import (
    ExampleCompoundMixedUiConfig,
    create_example_compound_mixed,
)

r = create_example_compound_mixed(
    rm,
    ExampleCompoundMixedUiConfig(compound_orientation="horizontal"),
)
layout.addWidget(r.widget)
```

### Подпись без регистра

```python
from frontend_module.components.controls.example_with_data_schema.label import (
    ExampleLabelUiConfig,
    create_example_label,
)

r = create_example_label(ExampleLabelUiConfig(label_text="Статус"))
layout.addWidget(r.widget)
```

## Паттерн

1. В схеме регистра — `ClassVar` `BINDING_REGISTER` и `BINDING_FIELD` для `BindingConfig`.
2. UI-схема — только отображение; пустой `label` → метаданные регистра (где применимо).
3. Адаптер — `binding_config_for_register`, `coerce_ui_schema`, маппинг в `*ViewConfig` / `Compound*Config`.
4. В `adapter.py` импортировать схемы только из `*.schemas` подпакета, не из его `__init__`, чтобы избежать циклов.
5. **v2/spinbox**: фасад `SpinBoxControl` (как `SliderControl` — обёртка над `NumericControl`).
