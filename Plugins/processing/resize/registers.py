"""ResizeRegisters — runtime-параметры ResizePlugin (live-tunable через GUI).

V3_MY_PURE: register = единый источник runtime-параметров + FieldMeta.
Plugin всегда работает через self._reg (managed или локальный), значит
правка scale_factor в inspector долетает через register_update и применяется
к живому процессу без рестарта.
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import register_schema
from multiprocess_framework.modules.process_module.plugins import FieldMeta
from multiprocess_framework.modules.process_module.plugins import SchemaBase


@register_schema("ResizeRegistersV3")
class ResizeRegisters(SchemaBase):
    """Параметры масштабирования — обновляются в runtime через register_update.

    Режим 1: относительное масштабирование (scale_factor).
    Режим 2: абсолютные размеры (target_width/target_height > 0 — приоритет).
    Интерполяция остаётся статичной (берётся из YAML в configure()).
    """

    # Относительный масштаб (runtime-tunable — GUI слайдер)
    scale_factor: Annotated[
        float,
        FieldMeta(
            "Scale Factor",
            info="Коэффициент масштаба (если target_* = 0)",
            min=0.1,
            max=4.0,
            transfer_k=10,
            round_k=2,
        ),
    ] = 1.0

    # Абсолютные размеры (0 = считать по scale_factor)
    target_width: Annotated[
        int,
        FieldMeta(
            "Target Width",
            info="Абсолютная ширина (0 = по scale_factor)",
            min=0,
            max=4096,
            unit="px",
        ),
    ] = 0
    target_height: Annotated[
        int,
        FieldMeta(
            "Target Height",
            info="Абсолютная высота (0 = по scale_factor)",
            min=0,
            max=4096,
            unit="px",
        ),
    ] = 0
