# -*- coding: utf-8 -*-
"""
Демо: схемы + адаптеры к контролам (все пользовательские компоненты + compound).

Расположение: ``frontend_module.components._examples``.

Паттерн адаптера: ``coerce_ui`` (3 ветки: None / экземпляр / dict) и ``BindingConfig`` из
``BINDING_*`` на классе регистра — без отдельного ``adapter_common``. См. README.md.
"""
from frontend_module.components._examples.checkbox import (
    EXAMPLE_CHECKBOX_ROUTING,
    ExampleCheckboxUiConfig,
    ExampleCheckboxValueRegister,
    checkbox_binding,
    checkbox_view_config_from_ui,
    coerce_ui as checkbox_coerce_ui,
    create_example_checkbox,
)
from frontend_module.components._examples.compound_mixed import (
    EXAMPLE_MIXED_ROUTING,
    ExampleCompoundMixedUiConfig,
    ExampleMixedBoolRegister,
    ExampleMixedFloatRegister,
    coerce_ui as compound_mixed_coerce_ui,
    create_example_compound_mixed,
)
from frontend_module.components._examples.compound_numeric import (
    EXAMPLE_BGR_ROUTING,
    ExampleBgrTripletRegister,
    ExampleCompoundNumericUiConfig,
    coerce_ui as compound_numeric_coerce_ui,
    compound_numeric_binding,
    compound_numeric_view_config_from_ui,
    create_example_compound_numeric,
)
from frontend_module.components._examples.group import (
    ExampleGroupRowUiConfig,
    GroupRowExampleResult,
    coerce_ui as group_row_coerce_ui,
    create_example_group_row,
)
from frontend_module.components._examples.label import (
    ExampleLabelUiConfig,
    LabelExampleResult,
    coerce_ui as label_coerce_ui,
    create_example_label,
    label_config_from_ui,
)
from frontend_module.components._examples.numeric import (
    EXAMPLE_NUMERIC_ROUTING,
    ExampleNumericUiConfig,
    ExampleNumericValueRegister,
    coerce_ui as numeric_coerce_ui,
    create_example_numeric,
    numeric_binding,
    numeric_view_config_from_ui,
)
from frontend_module.components._examples.slider import (
    EXAMPLE_SLIDER_ROUTING,
    ExampleSliderUiConfig,
    ExampleSliderValueRegister,
    coerce_ui as slider_coerce_ui,
    create_example_slider,
    slider_binding,
    slider_view_config_from_ui,
)
from frontend_module.components._examples.spinbox import (
    EXAMPLE_SPINBOX_ROUTING,
    ExampleSpinboxUiConfig,
    ExampleSpinboxValueRegister,
    coerce_ui as spinbox_coerce_ui,
    create_example_spinbox,
    spinbox_binding,
    spinbox_view_config_from_ui,
)

__all__ = [
    "EXAMPLE_BGR_ROUTING",
    "EXAMPLE_CHECKBOX_ROUTING",
    "EXAMPLE_MIXED_ROUTING",
    "EXAMPLE_NUMERIC_ROUTING",
    "EXAMPLE_SLIDER_ROUTING",
    "EXAMPLE_SPINBOX_ROUTING",
    "ExampleBgrTripletRegister",
    "ExampleCheckboxUiConfig",
    "ExampleCheckboxValueRegister",
    "ExampleCompoundMixedUiConfig",
    "ExampleCompoundNumericUiConfig",
    "ExampleGroupRowUiConfig",
    "ExampleLabelUiConfig",
    "ExampleNumericUiConfig",
    "ExampleNumericValueRegister",
    "ExampleMixedBoolRegister",
    "ExampleMixedFloatRegister",
    "ExampleSliderUiConfig",
    "ExampleSliderValueRegister",
    "ExampleSpinboxUiConfig",
    "ExampleSpinboxValueRegister",
    "GroupRowExampleResult",
    "LabelExampleResult",
    "checkbox_binding",
    "checkbox_coerce_ui",
    "checkbox_view_config_from_ui",
    "compound_mixed_coerce_ui",
    "compound_numeric_binding",
    "compound_numeric_coerce_ui",
    "create_example_group_row",
    "create_example_numeric",
    "compound_numeric_view_config_from_ui",
    "create_example_checkbox",
    "create_example_compound_mixed",
    "create_example_compound_numeric",
    "create_example_label",
    "create_example_slider",
    "create_example_spinbox",
    "group_row_coerce_ui",
    "label_coerce_ui",
    "numeric_binding",
    "numeric_coerce_ui",
    "numeric_view_config_from_ui",
    "label_config_from_ui",
    "slider_binding",
    "slider_coerce_ui",
    "slider_view_config_from_ui",
    "spinbox_binding",
    "spinbox_coerce_ui",
    "spinbox_view_config_from_ui",
]
