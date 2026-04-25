# -*- coding: utf-8 -*-
"""Составные контролы пакета control_v2 — CompoundNumericControl, CompoundControl, ControlFactory."""
from multiprocess_framework.modules.frontend_module.components.compound.config import (
    CompoundControlConfig,
    CompoundNumericConfig,
)
from multiprocess_framework.modules.frontend_module.components.compound.facade import (
    CompoundControl,
    CompoundControlResult,
    CompoundNumericControl,
    CompoundNumericControlResult,
    ControlFactory,
)
__all__ = [
    "CompoundNumericConfig",
    "CompoundControlConfig",
    "CompoundNumericControl",
    "CompoundNumericControlResult",
    "CompoundControl",
    "CompoundControlResult",
    "ControlFactory",
]
