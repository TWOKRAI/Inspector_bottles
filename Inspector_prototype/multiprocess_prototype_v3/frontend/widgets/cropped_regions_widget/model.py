# multiprocess_prototype_v3/frontend/widgets/cropped_regions_widget/model.py
"""Модель панели ROI: camera → region_name → [x, y, width, height]."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from frontend_module.interfaces import IRegistersManagerGui

from .schemas import CroppedRegionsTabUiConfig


@dataclass
class CroppedRegionsModel:
    registers_manager: Optional[IRegistersManagerGui]
    ui: CroppedRegionsTabUiConfig
    crop_regions_by_camera: Dict[str, Dict[str, List[int]]] = field(default_factory=dict)
    selected_camera: str = "default"
    camera_registry: Optional[Any] = None

    def current_regions(self) -> Dict[str, List[int]]:
        """Регионы выбранной камеры (изменяемый словарь)."""
        return self.crop_regions_by_camera.setdefault(self.selected_camera, {})
