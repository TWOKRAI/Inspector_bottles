# multiprocess_prototype_v3/frontend/widgets/post_processing_widget/model.py
"""Модель: camera → упорядоченный список регионов постобработки."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from multiprocess_framework.modules.frontend_module.interfaces import IRegistersManagerGui

from .schemas import PostProcessingTabUiConfig


@dataclass
class PostProcessingModel:
    registers_manager: Optional[IRegistersManagerGui]
    ui: PostProcessingTabUiConfig
    post_regions_by_camera: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    selected_camera: str = "default"
    clipboard_region: Optional[Dict[str, Any]] = None

    def current_regions(self) -> List[Dict[str, Any]]:
        """Список регионов выбранной камеры (изменяемый)."""
        return self.post_regions_by_camera.setdefault(self.selected_camera, [])
