# -*- coding: utf-8 -*-
"""Составные контролы v2 — CompoundNumericControl, CompoundControl, ControlFactory."""
from frontend_module.components.controls.v2.compound.config import (
    CompoundControlConfig,
    CompoundNumericConfig,
)
from frontend_module.components.controls.v2.compound.facade import (
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
