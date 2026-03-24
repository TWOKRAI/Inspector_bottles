# -*- coding: utf-8 -*-
"""Составные контролы пакета control_v2 — CompoundNumericControl, CompoundControl, ControlFactory."""
from frontend_module.components.compound.config import (
    CompoundControlConfig,
    CompoundNumericConfig,
)
from frontend_module.components.compound.facade import (
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
