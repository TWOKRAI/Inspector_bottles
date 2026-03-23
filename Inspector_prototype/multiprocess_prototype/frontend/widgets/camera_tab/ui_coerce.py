# multiprocess_prototype/frontend/widgets/camera_tab/ui_coerce.py
"""
Приведение конфигурации подписей UI к CameraTabUiConfig.

Использует coerce_schema_config из frontend_module. Принимает None, dict или
экземпляр; возвращает валидный CameraTabUiConfig.
"""

from __future__ import annotations

from typing import Optional, Union

from frontend_module.core.schema_config import coerce_schema_config

from .schemas import CameraTabUiConfig


def coerce_camera_ui(ui: Optional[Union[CameraTabUiConfig, dict]]) -> CameraTabUiConfig:
    """
    Нормализация ui: None → дефолт, dict → model_validate, экземпляр → как есть.

    Используется в MvpTabBase._coerce_ui; единый паттерн с другими вкладками.
    """
    return coerce_schema_config(ui, CameraTabUiConfig)
