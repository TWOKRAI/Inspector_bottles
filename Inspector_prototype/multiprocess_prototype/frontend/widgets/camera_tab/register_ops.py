# multiprocess_prototype/frontend/widgets/camera_tab/register_ops.py
"""
Работа с `IRegistersManagerGui` и схемой `CAMERA_REGISTER` без виджетов.

Сопоставление ключей API и полей регистра берётся из ``CameraTabUiConfig`` (schemas).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from frontend_module.interfaces import IRegistersManagerGui

from multiprocess_prototype.registers.schemas.camera_tab import CAMERA_REGISTER

if TYPE_CHECKING:
    from .schemas import CameraTabUiConfig


def set_camera_type_field(
    rm: Optional[IRegistersManagerGui], camera_type: str
) -> None:
    if rm is not None:
        rm.set_field_value(CAMERA_REGISTER, "camera_type", camera_type)


def persist_camera_type(camera_type: str) -> None:
    """
    Сохранить тип камеры на диск (preference / user config).

    Игнорирует ошибки импорта persistence или IO — не падаем при отсутствии модуля.
    """
    try:
        from multiprocess_prototype.persistence import set_camera_type

        set_camera_type(camera_type)
    except Exception:
        pass


def apply_hikvision_params_dict(
    rm: Optional[IRegistersManagerGui], params: Dict[str, Any], ui: "CameraTabUiConfig"
) -> None:
    """Записать в регистр значения из словаря ответа камеры (ключи из ui.hikvision_api_to_register)."""
    if not params or rm is None:
        return
    for api_key, field in ui.hikvision_api_field_pairs():
        if api_key in params:
            rm.set_field_value(CAMERA_REGISTER, field, float(params[api_key]))


def read_hikvision_triple_from_register(
    rm: Optional[IRegistersManagerGui], ui: "CameraTabUiConfig"
) -> Tuple[float, float, float]:
    """Кортеж (frame_rate, exposure, gain, …) по порядку hikvision_spinbox_rows из регистра."""
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
