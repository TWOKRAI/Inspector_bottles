# -*- coding: utf-8 -*-
"""
Пакет **control_v2** — контролы с архитектурой Traits + Presenter + View + Facade.

Расположение: ``frontend_module/components/control_v2/`` (рядом с пакетом ``controls/``).
Учебные схемы и адаптеры: подпакет ``examples`` (например ``examples/checkbox/``, ``examples/slider/``).

Принцип масштабирования: новый тип контрола = **View** (протокол ``IControlView``) +
**Presenter** (traits + порты ``IFieldBinding`` / ``IRegisterPort``) + **Facade** (``*.create``).
См. ``ARCHITECTURE.md`` и ``base/README.md``.
"""
from frontend_module.components.control_v2.base.config import (
    BaseControlConfig,
    BindingConfig,
    merge_config,
)
from frontend_module.components.control_v2.base.control_hooks import (
    ControlAccessDeniedEvent,
    ControlHooks,
    ControlWriteCommittedEvent,
    ControlWriteRejectedEvent,
    emit_access_denied,
)
from frontend_module.components.control_v2.base.traits import LegacySyncContext
from frontend_module.components.control_v2.checkbox import (
    CheckboxControl,
    CheckboxControlResult,
    CheckboxPresenter,
    CheckboxView,
    CheckboxViewConfig,
    checkbox_left,
    checkbox_right,
)
from frontend_module.components.control_v2.compound import (
    CompoundControl,
    CompoundControlConfig,
    CompoundControlResult,
    CompoundNumericConfig,
    CompoundNumericControl,
    CompoundNumericControlResult,
    ControlFactory,
)
from frontend_module.components.control_v2.group import (
    GroupConfig,
    LabeledNumericGroupConfig,
    label_bgr_slider_default,
    label_slider_default,
    label_spinbox_default,
)
from frontend_module.components.control_v2.label import LabelConfig
from frontend_module.components.control_v2.slider import (
    SliderConfig,
    SliderControl,
    SliderControlResult,
    SliderPresenter,
)
from frontend_module.components.control_v2.spinbox import (
    SpinBoxConfig,
    SpinBoxControl,
    SpinBoxControlResult,
    SpinBoxPresenter,
)
from frontend_module.components.control_v2.numeric import (
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
