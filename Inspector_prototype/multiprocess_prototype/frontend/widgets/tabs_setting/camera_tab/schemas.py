# multiprocess_prototype/frontend/widgets/tabs_setting/camera_tab/schemas.py
"""
Конфиг camera_tab: переключатель типа камеры (ComboBox).

Дочерние виджеты (simulator, webcam, hikvision) имеют собственные схемы.
"""

from __future__ import annotations

from typing import Dict, List

from pydantic import Field

from multiprocess_framework.refactored.modules.data_schema_module import (
    SchemaBase,
    register_schema,
)


def _default_camera_type_ids() -> List[str]:
    return ["simulator", "webcam", "hikvision"]


def _default_camera_type_labels() -> List[str]:
    return ["Simulator", "Webcam", "Hikvision"]


@register_schema("CameraTabUiConfig")
class CameraTabUiConfig(SchemaBase):
    """Конфиг переключателя типа камеры и порядка вкладок в стеке."""

    camera_type_register_ids: List[str] = Field(default_factory=_default_camera_type_ids)
    camera_type_options: List[str] = Field(default_factory=_default_camera_type_labels)
    camera_type_combo_min_width: int = 180
    group_camera_type: str = "Тип камеры"

    def camera_type_index_map(self) -> Dict[str, int]:
        return {rid: i for i, rid in enumerate(self.camera_type_register_ids)}

    def camera_type_for_combo_index(self, index: int) -> str:
        ids = self.camera_type_register_ids
        if not ids:
            return "simulator"
        if 0 <= index < len(ids):
            return ids[index]
        return ids[0]


def default_tab_item():
    from ..tab_item_config import TabItemConfig

    return TabItemConfig(id="camera", title="Камера", widget="camera")
