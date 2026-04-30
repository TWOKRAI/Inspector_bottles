# -*- coding: utf-8 -*-
"""
Базовые компоненты v2 — интерфейсы, конфиги, инфраструктура, traits.
"""
from multiprocess_framework.modules.frontend_module.components.base.control_hooks import (
    ControlAccessDeniedEvent,
    ControlHooks,
    ControlKind,
    ControlWriteCommittedEvent,
    ControlWriteRejectedEvent,
    emit_access_denied,
    emit_write_committed,
    emit_write_rejected,
)
from multiprocess_framework.modules.frontend_module.components.base.config import (
    BaseControlConfig,
    BindingConfig,
    LabelOverride,
    merge_config,
)
from multiprocess_framework.modules.frontend_module.components.base.touch_keyboard_config import (
    TouchKeyboardConfig,
    coerce_touch_keyboard,
)
from multiprocess_framework.modules.frontend_module.components.base.infrastructure import (
    RegisterAdapter,
    ValueTransformer,
    block_signals,
)
from multiprocess_framework.modules.frontend_module.components.base.interfaces import (
    IControlView,
    IFieldBinding,
    INumericView,
    IRegisterPort,
    RegistersManagerLike,
)
from multiprocess_framework.modules.frontend_module.components.base.traits import (
    AccessTrait,
    DebounceTrait,
    LegacySyncContext,
    LegacySyncTrait,
    SchemaTrait,
    SyncTrait,
)

__all__ = [
    "ControlAccessDeniedEvent",
    "ControlHooks",
    "ControlKind",
    "ControlWriteCommittedEvent",
    "ControlWriteRejectedEvent",
    "emit_access_denied",
    "emit_write_committed",
    "emit_write_rejected",
    "BaseControlConfig",
    "BindingConfig",
    "LabelOverride",
    "merge_config",
    "TouchKeyboardConfig",
    "coerce_touch_keyboard",
    "RegisterAdapter",
    "ValueTransformer",
    "block_signals",
    "IControlView",
    "IFieldBinding",
    "INumericView",
    "IRegisterPort",
    "RegistersManagerLike",
    "AccessTrait",
    "DebounceTrait",
    "LegacySyncContext",
    "LegacySyncTrait",
    "SchemaTrait",
    "SyncTrait",
]
