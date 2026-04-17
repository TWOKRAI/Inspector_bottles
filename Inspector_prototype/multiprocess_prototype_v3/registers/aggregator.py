# multiprocess_prototype_v3/registers/aggregator.py
"""Регистры агрегатора."""

from __future__ import annotations

from typing import Annotated, ClassVar

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    FieldRouting,
    RegisterDispatchMeta,
    SchemaBase,
)

from .names import AGGREGATOR_REGISTER

_AGG_R = FieldRouting(channel="control", process_targets=("aggregator",))


class AggregatorRegisters(SchemaBase):
    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("aggregator",),
    )
    report_interval: Annotated[
        float,
        FieldMeta("Report interval", min=0.5, max=30.0, unit="s", routing=_AGG_R),
    ] = 2.0


def register_name() -> str:
    return AGGREGATOR_REGISTER
