# -*- coding: utf-8 -*-
"""
Базовые компоненты v2 — интерфейсы, конфиги, инфраструктура, traits.
"""
from frontend_module.components.controls.v2.base.config import (
    BaseControlConfig,
    BindingConfig,
    LabelOverride,
    merge_config,
)
from frontend_module.components.controls.v2.base.infrastructure import (
    RegisterAdapter,
    ValueTransformer,
    block_signals,
)
from frontend_module.components.controls.v2.base.interfaces import (
    IControlView,
    INumericView,
)
from frontend_module.components.controls.v2.base.traits import (
    AccessTrait,
    DebounceTrait,
    LegacySyncContext,
    LegacySyncTrait,
    SchemaTrait,
    SyncTrait,
)

__all__ = [
    "BaseControlConfig",
    "BindingConfig",
    "LabelOverride",
    "merge_config",
    "RegisterAdapter",
    "ValueTransformer",
    "block_signals",
    "IControlView",
    "INumericView",
    "AccessTrait",
    "DebounceTrait",
    "LegacySyncContext",
    "LegacySyncTrait",
    "SchemaTrait",
    "SyncTrait",
]
