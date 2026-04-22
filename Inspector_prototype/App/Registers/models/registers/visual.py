# -*- coding: utf-8 -*-
"""
Регистры визуальных настроек интерфейса.
"""
from typing import Annotated

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    RegisterBase,
)


class VisualRegisters(RegisterBase):
    """Регистры настроек отображения изображения в UI."""

    image_scale: Annotated[
        float,
        FieldMeta(
            "Масштаб изображения",
            info="Коэффициент масштабирования изображения в окне просмотра.",
            min=0.1,
            max=2.0,
            transfer_k=10.0,
            round_k=1,
            examples=[0.25, 0.5, 1.0, 1.5, 2.0],
        ),
    ] = 0.5
