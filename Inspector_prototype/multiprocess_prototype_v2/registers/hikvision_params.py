# -*- coding: utf-8 -*-
"""Метаданные рядов параметров Hikvision для MVP-виджета (границы из GuiCameraRegisters)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from multiprocess_prototype_v2.registers.gui_camera_registers import GuiCameraRegisters

HIKVISION_SET_PARAMETER_REGISTER_FIELDS: tuple[str, ...] = (
    "hikvision_frame_rate",
    "hikvision_exposure_time",
    "hikvision_gain",
)

_REGISTER_TO_API_KEY = {
    "hikvision_frame_rate": "frame_rate",
    "hikvision_exposure_time": "exposure_time",
    "hikvision_gain": "gain",
}

_DEFAULT_LABELS = {
    "hikvision_frame_rate": "Frame rate",
    "hikvision_exposure_time": "Exposure",
    "hikvision_gain": "Gain",
}


@dataclass(frozen=True)
class HikvisionParamRow:
    register_field: str
    api_key: str
    label: str
    default_value: float
    min_val: float
    max_val: float
    placeholder: str = ""
    format_spec: str = ""


def build_hikvision_param_rows(
    *,
    param_display: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[HikvisionParamRow]:
    disp = param_display or {}
    inst = GuiCameraRegisters()
    rows: List[HikvisionParamRow] = []
    for reg_field in HIKVISION_SET_PARAMETER_REGISTER_FIELDS:
        meta = GuiCameraRegisters.get_field_meta(reg_field)
        min_v = float(meta.min) if meta is not None and meta.min is not None else 0.0
        max_v = float(meta.max) if meta is not None and meta.max is not None else 1e9
        dv = float(getattr(inst, reg_field, 0.0))
        ov = disp.get(reg_field) or {}
        rows.append(
            HikvisionParamRow(
                register_field=reg_field,
                api_key=_REGISTER_TO_API_KEY[reg_field],
                label=str(ov.get("label", _DEFAULT_LABELS[reg_field])),
                default_value=dv,
                min_val=min_v,
                max_val=max_v,
                placeholder=str(ov.get("placeholder", "")),
                format_spec=str(ov.get("format_spec", "")),
            )
        )
    return rows
