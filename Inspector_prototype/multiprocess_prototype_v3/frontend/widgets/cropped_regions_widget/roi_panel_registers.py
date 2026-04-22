# multiprocess_prototype_v3/frontend/widgets/cropped_regions_widget/roi_panel_registers.py
"""
Локальная схема ROI-панели: x, y, width, height для NumericControl.

Не входит в фабрику процессов — только экземпляр внутри CroppedAreaControls + RegistersManager.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, ClassVar

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    RegisterDispatchMeta,
    SchemaBase,
    register_schema,
)

from .params import CroppedParamKey, DEFAULT_CROPPED_PARAMS


class CroppedRoiLocalRegisterName(StrEnum):
    """Local RegistersManager register name (not the processor register)."""

    PANEL = "cropped_roi_panel"


CROPPED_ROI_PANEL_REGISTER = CroppedRoiLocalRegisterName.PANEL.value

NUMERIC_ROI_FIELD_NAMES: tuple[str, ...] = (
    CroppedParamKey.X.value,
    CroppedParamKey.Y.value,
    CroppedParamKey.WIDTH.value,
    CroppedParamKey.HEIGHT.value,
)


@register_schema("CroppedRoiPanelRegisters")
class CroppedRoiPanelRegisters(SchemaBase):
    """Четыре координаты прямоугольника ROI."""

    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=(),
    )

    x: Annotated[
        int,
        FieldMeta("x", info="Левый верхний угол X", min=0.0, max=4096.0),
    ] = DEFAULT_CROPPED_PARAMS["x"]

    y: Annotated[
        int,
        FieldMeta("y", info="Левый верхний угол Y", min=0.0, max=4096.0),
    ] = DEFAULT_CROPPED_PARAMS["y"]

    width: Annotated[
        int,
        FieldMeta("Ширина", info="Ширина ROI", min=0.0, max=4096.0),
    ] = DEFAULT_CROPPED_PARAMS["width"]

    height: Annotated[
        int,
        FieldMeta("Высота", info="Высота ROI", min=0.0, max=4096.0),
    ] = DEFAULT_CROPPED_PARAMS["height"]
