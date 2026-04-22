# -*- coding: utf-8 -*-
"""
Регистры управления конвейером.
"""
from typing import Annotated

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    RegisterBase,
)


class ConveyorRegisters(RegisterBase):
    """Регистры управления конвейером."""

    enabled: Annotated[
        bool,
        FieldMeta(
            "Включить конвейер",
            info="Включить / отключить движение конвейера.",
            routing={"channel": "control_conveyor"},
        ),
    ] = False

    speed: Annotated[
        float,
        FieldMeta(
            "Скорость конвейера",
            info="Скорость движения ленты конвейера.",
            unit="%",
            min=0.0,
            max=100.0,
            transfer_k=1.0,
            round_k=1,
            routing={"channel": "control_conveyor"},
        ),
    ] = 0.0
