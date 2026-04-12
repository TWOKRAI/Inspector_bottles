# multiprocess_prototype_v3/registers/processor_registers.py
"""Регистры процесса анализа кадра."""

from __future__ import annotations

from typing import Annotated, ClassVar

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    FieldRouting,
    RegisterDispatchMeta,
    SchemaBase,
)

from .names import PROCESSOR_REGISTER

_PROC_R = FieldRouting(channel="control", process_targets=("processor",))


class ProcessorRegisters(SchemaBase):
    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("processor",),
    )
    brightness_threshold: Annotated[
        int,
        FieldMeta("Brightness threshold", min=0, max=255, routing=_PROC_R),
    ] = 128
    enabled: Annotated[bool, FieldMeta("Enabled", routing=_PROC_R)] = True


def register_name() -> str:
    return PROCESSOR_REGISTER
