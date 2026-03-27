# -*- coding: utf-8 -*-
"""
Параметры Hikvision для Set/Get: порядок полей в CAMERA_REGISTER и маппинг на ключи API.

Источник границ и дефолтов — поля :class:`CameraRegisters` и их FieldMeta.
Placeholder и format_spec — дефолты ниже; переопределение через UI-конфиг виджета.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .camera import CameraRegisters

# Порядок для GuiCommandHandler.send_set_parameters(frame_rate, exposure_time, gain)
HIKVISION_SET_PARAMETER_REGISTER_FIELDS: Tuple[str, ...] = (
    "hikvision_frame_rate",
    "hikvision_exposure_time",
    "hikvision_gain",
)

# Ключ в ответе камеры / payload IPC ↔ имя поля в регистре
REGISTER_FIELD_TO_API_KEY: Dict[str, str] = {
    "hikvision_frame_rate": "frame_rate",
    "hikvision_exposure_time": "exposure_time",
    "hikvision_gain": "gain",
}

API_KEY_TO_REGISTER_FIELD: Dict[str, str] = {
    v: k for k, v in REGISTER_FIELD_TO_API_KEY.items()
}

# Fallback UI (не дублируют min/max — только отображение)
_DEFAULT_PLACEHOLDER: Dict[str, str] = {
    "hikvision_frame_rate": "FPS",
    "hikvision_exposure_time": "μs",
    "hikvision_gain": "dB",
}
_DEFAULT_FORMAT: Dict[str, str] = {
    "hikvision_frame_rate": ".1f",
    "hikvision_exposure_time": ".0f",
    "hikvision_gain": ".1f",
}


@dataclass(frozen=True)
class HikvisionParamRow:
    """Один ряд параметра для spinbox/line edit и модели (данные из регистра)."""

    register_field: str
    api_key: str
    min_val: float
    max_val: float
    default_value: float
    label: str
    placeholder: str
    format_spec: str


def _float_meta_bounds(field_name: str) -> Tuple[float, float]:
    meta = CameraRegisters.get_field_meta(field_name)
    if meta is None or meta.min is None or meta.max is None:
        return (0.0, 1.0)
    return (float(meta.min), float(meta.max))


def _label_for_field(field_name: str) -> str:
    meta = CameraRegisters.get_field_meta(field_name)
    if meta is None or not meta.description:
        return f"{field_name}:"
    d = str(meta.description).strip()
    return d if d.endswith(":") else f"{d}:"


def build_hikvision_param_rows(
    *,
    param_display: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[HikvisionParamRow]:
    """
    Построить ряды из CameraRegisters (defaults + FieldMeta min/max).

    ``param_display`` — опционально: register_field → {placeholder, format_spec, label}.
    """
    param_display = param_display or {}
    reg_defaults = CameraRegisters()
    out: List[HikvisionParamRow] = []
    for fname in HIKVISION_SET_PARAMETER_REGISTER_FIELDS:
        api_key = REGISTER_FIELD_TO_API_KEY[fname]
        min_v, max_v = _float_meta_bounds(fname)
        default_v = float(getattr(reg_defaults, fname))
        disp = param_display.get(fname) or {}
        placeholder = str(disp.get("placeholder", _DEFAULT_PLACEHOLDER.get(fname, "")))
        format_spec = str(disp.get("format_spec", _DEFAULT_FORMAT.get(fname, ".4f")))
        label = str(disp.get("label", _label_for_field(fname)))
        out.append(
            HikvisionParamRow(
                register_field=fname,
                api_key=api_key,
                min_val=min_v,
                max_val=max_v,
                default_value=default_v,
                label=label,
                placeholder=placeholder,
                format_spec=format_spec,
            )
        )
    return out