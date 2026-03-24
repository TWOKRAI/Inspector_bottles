# -*- coding: utf-8 -*-
"""
Регистры процесса обработки кадров.
"""
from typing import Annotated

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    RegisterBase,
)


class FrameProcessRegisters(RegisterBase):
    """Регистры управления процессом обработки кадров."""

    enabled: Annotated[
        bool,
        FieldMeta(
            "Включить обработку кадров",
            info="Включить / отключить поток обработки кадров.",
            routing={"channel": "control_frame_process"},
        ),
    ] = True

    fps_limit: Annotated[
        int,
        FieldMeta(
            "Ограничение FPS",
            info="Максимальная частота обработки кадров (0 — без ограничений).",
            unit="кадр/с",
            min=0,
            max=120,
            routing={"channel": "control_frame_process"},
        ),
    ] = 0
