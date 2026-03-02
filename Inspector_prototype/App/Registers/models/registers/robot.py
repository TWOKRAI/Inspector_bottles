# -*- coding: utf-8 -*-
"""
Регистры управления роботом.
"""
from typing import Annotated

from multiprocess_framework.refactored.modules.data_schema_module import (
    FieldMeta,
    RegisterBase,
)


class RobotRegisters(RegisterBase):
    """Регистры управления промышленным роботом."""

    enabled: Annotated[
        bool,
        FieldMeta(
            "Включить робота",
            info="Включить / отключить управление роботом.",
            routing={"channel": "control_robot"},
        ),
    ] = False

    speed: Annotated[
        float,
        FieldMeta(
            "Скорость движения",
            info="Скорость движения манипулятора (% от максимума).",
            unit="%",
            min=0.0,
            max=100.0,
            transfer_k=1.0,
            round_k=0,
            routing={"channel": "control_robot"},
        ),
    ] = 10.0

    home_on_start: Annotated[
        bool,
        FieldMeta(
            "Движение в HOME при старте",
            info="Выполнить движение в начальную позицию при инициализации.",
            routing={"channel": "control_robot"},
        ),
    ] = True
