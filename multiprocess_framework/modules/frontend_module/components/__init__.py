# -*- coding: utf-8 -*-
"""
Примитивы контролов — Traits + Presenter + View + Facade.

Учебные схемы и адаптеры: подпакет ``examples``. Составной UI (вкладки, BaseWidget) —
``frontend_module.widgets``.

Принцип масштабирования: новый тип контрола = **View** (протокол ``IControlView``) +
**Presenter** (traits + порты ``IFieldBinding`` / ``IRegisterPort``) + **Facade** (``*.create``).
См. ``ARCHITECTURE.md`` и ``base/README.md``.
"""
from multiprocess_framework.modules.frontend_module.components.base.config import (
    BaseControlConfig,
    BindingConfig,
    merge_config,
)
from multiprocess_framework.modules.frontend_module.components.base.control_hooks import (
    ControlAccessDeniedEvent,
    ControlHooks,
    ControlWriteCommittedEvent,
    ControlWriteRejectedEvent,
    emit_access_denied,
)
from multiprocess_framework.modules.frontend_module.components.base.traits import LegacySyncContext
from multiprocess_framework.modules.frontend_module.components.checkbox import (
    CheckboxControl,
    CheckboxControlResult,
    CheckboxPresenter,
    CheckboxView,
    CheckboxViewConfig,
    checkbox_left,
    checkbox_right,
)
from multiprocess_framework.modules.frontend_module.components.compound import (
    CompoundControl,
    CompoundControlConfig,
    CompoundControlResult,
    CompoundNumericConfig,
    CompoundNumericControl,
    CompoundNumericControlResult,
    ControlFactory,
)
from multiprocess_framework.modules.frontend_module.components.group import (
    GroupConfig,
    LabeledNumericGroupConfig,
    label_bgr_slider_default,
    label_slider_default,
    label_spinbox_default,
)
from multiprocess_framework.modules.frontend_module.components.label import LabelConfig
from multiprocess_framework.modules.frontend_module.components.slider import (
    SliderConfig,
    SliderControl,
    SliderControlResult,
    SliderPresenter,
)
from multiprocess_framework.modules.frontend_module.components.spinbox import (
    SpinBoxConfig,
    SpinBoxControl,
    SpinBoxControlResult,
    SpinBoxPresenter,
)
from multiprocess_framework.modules.frontend_module.components.numeric import (
    NumericControl,
    NumericControlResult,
    NumericPresenter,
    NumericViewConfig,
    bgr_slider_default,
    slider_default,
    spinbox_default,
)

__all__ = [
    "ControlAccessDeniedEvent",
    "ControlHooks",
    "ControlWriteCommittedEvent",
    "ControlWriteRejectedEvent",
    "emit_access_denied",
    "NumericControl",
    "NumericControlResult",
    "NumericPresenter",
    "CheckboxView",
    "CheckboxPresenter",
    "CheckboxControl",
    "CheckboxControlResult",
    "CompoundNumericControl",
    "CompoundNumericControlResult",
    "CompoundControl",
    "CompoundControlResult",
    "ControlFactory",
    "LegacySyncContext",
    "BindingConfig",
    "NumericViewConfig",
    "CheckboxViewConfig",
    "CompoundNumericConfig",
    "CompoundControlConfig",
    "BaseControlConfig",
    "merge_config",
    "slider_default",
    "spinbox_default",
    "bgr_slider_default",
    "checkbox_left",
    "checkbox_right",
    "LabelConfig",
    "SliderConfig",
    "SliderControl",
    "SliderControlResult",
    "SliderPresenter",
    "SpinBoxConfig",
    "SpinBoxControl",
    "SpinBoxControlResult",
    "SpinBoxPresenter",
    "GroupConfig",
    "LabeledNumericGroupConfig",
    "label_slider_default",
    "label_spinbox_default",
    "label_bgr_slider_default",
]
