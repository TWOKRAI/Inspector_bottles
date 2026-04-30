# multiprocess_prototype/registers/producer.py
"""Регистры producer — FieldRouting → process_targets producer."""

from __future__ import annotations

from typing import Annotated, ClassVar

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    FieldRouting,
    RegisterDispatchMeta,
    SchemaBase,
)

from .names import PRODUCER_REGISTER

_PROD_R = FieldRouting(channel="control", process_targets=("producer",))


class ProducerRegisters(SchemaBase):
    """Поля UI/консоли для процесса producer."""

    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("producer",),
    )
    interval: Annotated[
        float,
        FieldMeta("Interval", min=0.1, max=5.0, unit="s", routing=_PROD_R),
    ] = 0.5
    message_prefix: Annotated[
        str,
        FieldMeta("Message prefix", routing=_PROD_R),
    ] = "msg"
    enabled: Annotated[
        bool,
        FieldMeta("Enabled", routing=_PROD_R),
    ] = True


def register_name() -> str:
    return PRODUCER_REGISTER
