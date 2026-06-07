"""CameraServiceRegisters — runtime-tunable параметры камеры (inspector subset).

Это РЕДАКТИРУЕМЫЙ В ИНСПЕКТОРЕ subset (плагин = менее подробный, чем
Services-фасад). Полный каталог физических параметров — в
backends/webcam_controls.py (WEBCAM_PARAMS), его использует Services-фасад
через generic-команду `set_param`.

ВАЖНО: дефолты этих полей — лишь стартовая позиция UI (desired), они НЕ
форсятся на камеру при открытии. Камера применяет параметр только когда
пользователь его меняет (set_config → backend.set_param) или когда значение
явно задано в рецепте (plugin_config `params`). Поэтому desired (register) и
actual (cap.get) могут расходиться для нетронутых полей — это инвариант, actual
показывается отдельно.
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import register_schema
from multiprocess_framework.modules.process_module.plugins import FieldMeta
from multiprocess_framework.modules.process_module.plugins import SchemaBase


@register_schema("CameraServiceRegistersV1")
class CameraServiceRegisters(SchemaBase):
    """Tunable-параметры камеры для live-правки (subset)."""

    fps: Annotated[
        int,
        FieldMeta(
            "Целевой FPS",
            info="Целевая частота кадров (cap.set FPS)",
            min=1,
            max=120,
            unit="fps",
            widget="slider",
        ),
    ] = 25
    mjpg: Annotated[
        bool,
        FieldMeta(
            "MJPG",
            info="Кодек MJPG снимает потолок ~15fps DirectShow (нужен реопен)",
            widget="checkbox",
        ),
    ] = False
    exposure: Annotated[
        int,
        FieldMeta(
            "Экспозиция",
            info="log2 экспозиция (DirectShow), меньше = темнее",
            min=-13,
            max=0,
            unit="log2",
            widget="slider",
        ),
    ] = -6
    gain: Annotated[
        int,
        FieldMeta(
            "Усиление",
            min=0,
            max=255,
            widget="slider",
        ),
    ] = 0
    brightness: Annotated[
        int,
        FieldMeta(
            "Яркость",
            min=0,
            max=255,
            widget="slider",
        ),
    ] = 128
    contrast: Annotated[
        int,
        FieldMeta(
            "Контраст",
            min=0,
            max=255,
            widget="slider",
        ),
    ] = 128
