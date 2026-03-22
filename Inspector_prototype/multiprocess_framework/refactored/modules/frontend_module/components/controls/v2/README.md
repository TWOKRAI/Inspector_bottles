# controls v2 — архитектура и документация

## Структура папок

```
v2/
├── base/              # База: интерфейсы, конфиги, инфраструктура, traits
├── label/             # Подпись (QLabel) — отдельный компонент
├── slider/            # Слайдер (QLineEdit + QSlider) — value-контрол
├── spinbox/           # Спинбокс (QDoubleSpinBox) — value-контрол
├── checkbox/          # Чекбокс: CheckboxView, CheckboxViewConfig, CheckboxControl
│   ├── config.py      # CheckboxViewConfig
│   ├── view.py        # CheckboxView (QLabel + QCheckBox)
│   ├── presenter.py   # CheckboxPresenter
│   ├── facade.py      # CheckboxControl
│   └── defaults.py   # checkbox_left, checkbox_right
├── numeric/           # Фасад числовых: Group(Label + Slider/SpinBox)
├── group/             # Группы: Label+Slider, Label+SpinBox
└── compound/          # Составные: BGR, mixed layouts
```

---

## Mermaid: карта зависимостей

```mermaid
flowchart TB
    subgraph Примитивы
        Label[label/ LabelView]
        Slider[slider/ SliderValueView]
        Spinbox[spinbox/ SpinBoxValueView]
        Checkbox[checkbox/ CheckboxView]
    end

    subgraph Группы
        Group[group/ LabeledNumericGroupView]
    end

    subgraph Фасады
        Numeric[numeric/ NumericControl]
        CheckboxControl[checkbox/]
        Compound[compound/ CompoundControl]
    end

    Label --> Group
    Slider --> Group
    Spinbox --> Group
    Group --> Numeric
    Checkbox --> CheckboxControl
    Numeric --> Compound
    CheckboxControl --> Compound
```

---

## Диаграмма: карта компонентов

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           controls v2 — компоненты                                │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│   ПРИМИТИВЫ              ГРУППЫ                    ФАСАДЫ                       │
│   ───────────           ───────                    ───────                       │
│                                                                                  │
│   ┌─────────┐           ┌──────────────┐          ┌─────────────────┐           │
│   │  label/ │──────────▶│    group/    │◀─────────│   numeric/      │           │
│   │LabelView│           │ Label+Slider │          │ NumericControl  │           │
│   └─────────┘           │ Label+SpinBox│          │ (Slider|SpinBox) │           │
│         │               └──────────────┘          └────────┬────────┘           │
│         │                          ▲                       │                     │
│   ┌─────┴─────┐                    │                       │                     │
│   │  slider/  │────────────────────┘                       │                     │
│   │SliderValue│                                             │                     │
│   └───────────┘                                             │                     │
│   ┌───────────┐                                             │                     │
│   │ spinbox/  │─────────────────────────────────────────────┘                     │
│   │SpinBoxValue│                                                                  │
│   └───────────┘                                                                  │
│                                                                                  │
│   ┌─────────────┐                                    ┌─────────────────┐         │
│   │  checkbox/  │  Чекбокс                           │   compound/     │         │
│   │ CheckboxView│───────────────────────────────────▶│ CompoundControl │         │
│   │ CheckboxCtrl│                                    │ ControlFactory  │         │
│   └─────────────┘                                    └─────────────────┘         │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Диаграмма: слой Base

```
┌────────────────────────────────────────────────────────────────┐
│                         base/                                   │
├────────────────────────────────────────────────────────────────┤
│  interfaces.py     │ IControlView[T], INumericView              │
│  config.py         │ BaseControlConfig, BindingConfig,          │
│                    │ LabelOverride, merge_config                │
│  infrastructure/  │ RegisterAdapter, ValueTransformer,         │
│                    │ block_signals                              │
│  traits/          │ SchemaTrait, SyncTrait, DebounceTrait,      │
│                    │ AccessTrait, LegacySyncTrait               │
└────────────────────────────────────────────────────────────────┘
```

---

## Диаграмма: поток создания NumericControl

```
  NumericControl.create(rm, binding, NumericViewConfig)
                    │
                    ▼
         ┌──────────────────────┐
         │ RegisterAdapter(rm)   │
         └──────────┬───────────┘
                    │
                    ▼
         ┌──────────────────────┐     view_type
         │ NumericPresenter      │───────────────┐
         │ (Schema+Sync+Debounce)│               │
         └──────────┬───────────┘               │
                    │                           ▼
                    │              ┌────────────────────────────┐
                    │              │ create_labeled_numeric_view│
                    │              │ (view_type, value_config)  │
                    │              └────────────┬───────────────┘
                    │                           │
                    │              ┌────────────┴────────────┐
                    │              │                        │
                    │         slider?                  spinbox?
                    │              │                        │
                    │    SliderValueView          SpinBoxValueView
                    │              │                        │
                    │              └────────────┬──────────┘
                    │                           │
                    │              ┌────────────▼────────────┐
                    │              │ LabeledNumericGroupView  │
                    │              │ = LabelView + ValueView   │
                    │              └────────────┬────────────┘
                    │                           │
                    └──────── attach_view ◀─────┘
                              │
                              ▼
                    result.widget → layout.addWidget()
```

---

## Диаграмма: поток создания CheckboxControl

```
  CheckboxControl.create(rm, binding, CheckboxViewConfig)
                    │
                    ▼
         ┌──────────────────────┐
         │ RegisterAdapter(rm)   │
         └──────────┬───────────┘
                    │
                    ▼
         ┌──────────────────────┐
         │ CheckboxPresenter     │
         │ (Schema+Sync+Access)   │
         └──────────┬───────────┘
                    │
                    ▼
         ┌──────────────────────┐
         │ CheckboxView          │  ← QLabel + QCheckBox
         │ (position: left/right)│
         └──────────┬───────────┘
                    │
                    └── attach_view
                              │
                              ▼
                    result.widget → layout.addWidget()
```

---

## Таблица компонентов

| Папка | Компонент | Config | View | Facade |
|-------|-----------|--------|------|--------|
| **base/** | — | BaseControlConfig, BindingConfig | IControlView, INumericView | — |
| **label/** | Подпись | LabelConfig | LabelView | — |
| **slider/** | Слайдер | SliderConfig | SliderValueView | — |
| **spinbox/** | Спинбокс | SpinBoxConfig | SpinBoxValueView | — |
| **checkbox/** | **Чекбокс** | CheckboxViewConfig | CheckboxView | CheckboxControl |
| **numeric/** | Числовой | NumericViewConfig | Group(Label+Value) | NumericControl |
| **group/** | Группа | GroupConfig, LabeledNumericGroupConfig | LabeledNumericGroupView | — |
| **compound/** | Составной | CompoundNumericConfig, CompoundControlConfig | — | CompoundControl, ControlFactory |

---

## Примеры использования

### 1. Числовой слайдер

```python
from frontend_module.components.controls import (
    NumericControl,
    BindingConfig,
    NumericViewConfig,
)

result = NumericControl.create(
    registers_manager,
    BindingConfig(register_name="processor", field_name="min_area"),
    NumericViewConfig(view_type="slider", show_ticks=True),
)
layout.addWidget(result.widget)
```

### 2. Чекбокс

```python
from frontend_module.components.controls import (
    CheckboxControl,
    BindingConfig,
    CheckboxViewConfig,
)

result = CheckboxControl.create(
    registers_manager,
    BindingConfig(register_name="renderer", field_name="show_mask"),
    CheckboxViewConfig(position="left"),  # или "right", "top", "bottom"
)
layout.addWidget(result.widget)
```

### 3. Спинбокс вместо слайдера

```python
result = NumericControl.create(
    rm,
    BindingConfig("processor", "threshold"),
    NumericViewConfig(view_type="spinbox"),
)
layout.addWidget(result.widget)
```

### 4. BGR-слайдеры (составной)

```python
from frontend_module.components.controls import (
    CompoundNumericControl,
    CompoundNumericConfig,
    BindingConfig,
    NumericViewConfig,
)

cfg = CompoundNumericConfig(
    binding=BindingConfig("processor", "color_lower"),
    labels=["B", "G", "R"],
    view_config=NumericViewConfig(min_val=0, max_val=255),
)
result = CompoundNumericControl.create(rm, cfg)
layout.addWidget(result.widget)
```

### 5. Дефолты и merge_config

```python
from frontend_module.components.controls import (
    bgr_slider_default,
    merge_config,
    NumericViewConfig,
)

config = merge_config(bgr_slider_default, NumericViewConfig(label="Канал B"))
result = NumericControl.create(rm, binding, config)
```

### 6. Группа с отдельными конфигами (Slider/SpinBox)

```python
from frontend_module.components.controls.v2 import (
    LabeledNumericGroupConfig,
    LabelConfig,
    SliderConfig,
    SpinBoxConfig,
)

# Label слева + Slider
cfg = LabeledNumericGroupConfig(
    label_config=LabelConfig(position="left"),
    value_config=SliderConfig(show_ticks=True),
)
```

---

## Диаграмма: связь типов

```
                    ┌─────────────────┐
                    │ BaseControlConfig│
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│  SliderConfig │   │ SpinBoxConfig  │   │CheckboxViewCfg│
└───────────────┘   └───────────────┘   └───────────────┘
        │                    │                    │
        └────────────────────┼────────────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ NumericViewConfig│  ← view_type + объединённые поля
                    │ (facade)         │
                    └─────────────────┘
```

---

## Рекомендации

- **Добавить новый value-контрол** (например, ComboBox): создать папку `combobox/` с config, view, defaults; добавить в `group/` и `numeric/facade`.
- **Добавить новый тип контрола** (например, ColorPicker): папка `color_picker/` по аналогии с `checkbox/` (config, view, presenter, facade).
- **Кастомная группа**: использовать `GroupConfig(children=[...])` с произвольным списком конфигов.
