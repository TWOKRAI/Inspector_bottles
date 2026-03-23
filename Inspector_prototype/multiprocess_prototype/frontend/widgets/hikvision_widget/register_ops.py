# multiprocess_prototype/frontend/widgets/hikvision_widget/register_ops.py
"""Работа с CAMERA_REGISTER для Hikvision параметров."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from frontend_module.interfaces import IRegistersManagerGui

from multiprocess_prototype.registers.schemas.camera_tab import CAMERA_REGISTER

if TYPE_CHECKING:
    from .schemas import HikvisionUiConfig


def apply_hikvision_params_dict(
    rm: Optional[IRegistersManagerGui], params: Dict[str, Any], ui: "HikvisionUiConfig"
) -> None:
    """Записать в регистр значения из словаря ответа камеры."""
    if not params or rm is None:
        return
    for api_key, field in ui.hikvision_api_field_pairs():
        if api_key in params:
            rm.set_field_value(CAMERA_REGISTER, field, float(params[api_key]))


def read_hikvision_triple_from_register(
    rm: Optional[IRegistersManagerGui], ui: "HikvisionUiConfig"
) -> Tuple[float, float, float]:
    """Кортеж (frame_rate, exposure, gain) из регистра."""
    if rm is None:
        return tuple(s.read_fallback_default for s in ui.hikvision_spinbox_rows)
    reg = rm.get_register(CAMERA_REGISTER)
    if not reg:
        return tuple(s.read_fallback_default for s in ui.hikvision_spinbox_rows)
    out: list[float] = []
    for spec in ui.hikvision_spinbox_rows:
        v = getattr(reg, spec.register_field, spec.read_fallback_default)
        out.append(float(v))
    return tuple(out)
