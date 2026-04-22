# components.examples

Учебный пакет (ранее `controls/example_with_data_schema`): схемы `SchemaBase` и адаптеры ко **всем** видимым частям контролов: `label`, `checkbox`, `slider`, `spinbox`, `numeric`, `group` (только виджет), `compound_*`. Слой `base/` (traits, порты) подключается через эти фасады — отдельного «примера base» нет.

Содержит **только** схемы и сборку виджетов; без отдельного config-слоя приложения.

## Структура

```
components/examples/
├── checkbox/
├── slider/
├── spinbox/
├── numeric/            # NumericControl (view_type slider|spinbox)
├── group/              # create_labeled_numeric_view — без регистра
├── compound_numeric/   # BGR + CompoundNumericControl
├── compound_mixed/     # CompoundControl (bool + float)
└── label/              # только LabelView (без регистра)
```

- **schemas** — `BINDING_*` на классе регистра, где есть регистр; для `label/` и `group/` только UI.
- **adapter** — `*_binding()` + явный `BindingConfig`, `coerce_ui()` (три ветки), `*_view_config_from_ui()`, `create_example_*()`.

## Примеры

### Checkbox / Slider / Spinbox

```python
from frontend_module.components.examples import (
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
from frontend_module.components.examples.compound_numeric import (
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
from frontend_module.components.examples.compound_mixed import (
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
from frontend_module.components.examples.label import (
    ExampleLabelUiConfig,
    create_example_label,
)

r = create_example_label(ExampleLabelUiConfig(label_text="Статус"))
layout.addWidget(r.widget)
```

### NumericControl (один скаляр, тип виджета из UI)

```python
from frontend_module.components.examples.numeric import (
    ExampleNumericUiConfig,
    create_example_numeric,
)

r = create_example_numeric(
    rm,
    ExampleNumericUiConfig(numeric_view_type="spinbox", numeric_label="Уровень"),
)
layout.addWidget(r.widget)
```

### Group: только «метка + slider/spinbox» (без `RegistersManager`)

```python
from frontend_module.components.examples.group import (
    ExampleGroupRowUiConfig,
    create_example_group_row,
)

r = create_example_group_row(
    ExampleGroupRowUiConfig(row_label="Параметр", view_type="slider", show_ticks=True)
)
layout.addWidget(r.widget)
```

## Паттерн

1. В схеме регистра — `ClassVar` `BINDING_REGISTER` и `BINDING_FIELD`; в адаптере — `BindingConfig(register_name=..., field_name=..., access_level=...)`.
2. UI-схема — только отображение; пустой `label` → метаданные регистра (где применимо).
3. `coerce_ui`: `None` → дефолтная модель, иначе экземпляр или `model_validate(dict)`.
4. В `adapter.py` импортировать схемы только из `*.schemas` подпакета, не из его `__init__`, чтобы избежать циклов.
5. **SpinBoxControl** / **SliderControl** — отдельные фасады; **NumericControl** — общий вход с `view_type`.

**ControlFactory** (программная сборка составных контролов) — в `components.compound`; отдельной папки в `examples/` нет: см. использование пар binding+config в `compound_mixed/`.
