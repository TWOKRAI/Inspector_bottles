# multiprocess_prototype/frontend/widgets/tabs_setting/camera_tab/schemas.py
"""
Конфиг camera_tab: переключатель типа камеры (ComboBox).

Дочерние виджеты (simulator, webcam, hikvision) имеют собственные схемы.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import Field

from multiprocess_prototype.camera_policy import (
    DEFAULT_CAMERA_TYPE,
    WEBCAM_ENUM_DEFAULT_MAX_INDEX,
    WEBCAM_ENUM_HARD_CAP,
)

from multiprocess_framework.refactored.modules.data_schema_module import (
    SchemaBase,
    register_schema,
)


def _default_camera_type_ids() -> List[str]:
    from multiprocess_prototype.camera_policy import CAMERA_TYPES
    return list(CAMERA_TYPES)


def _default_camera_type_labels() -> List[str]:
    from multiprocess_prototype.camera_policy import CAMERA_TYPE_LABELS
    return list(CAMERA_TYPE_LABELS)


@register_schema("CameraTabUiConfig")
class CameraTabUiConfig(SchemaBase):
    """Конфиг переключателя типа камеры и порядка вкладок в стеке."""

    camera_type_register_ids: List[str] = Field(default_factory=_default_camera_type_ids)
    camera_type_options: List[str] = Field(default_factory=_default_camera_type_labels)
    camera_type_combo_min_width: int = 180
    group_camera_type: str = "Тип камеры"

    webcam_enum_max_index: int = Field(
        default=WEBCAM_ENUM_DEFAULT_MAX_INDEX,
        ge=1,
        le=WEBCAM_ENUM_HARD_CAP,
        description="Опрос OpenCV [0..N-1] при enum_devices в режиме Webcam; Hikvision SDK список целиком.",
    )
    # Dict at Boundary → HikvisionWidget приводит к HikvisionUiConfig (без циклического импорта схем).
    hikvision: Dict[str, Any] = Field(default_factory=dict)

    def camera_type_index_map(self) -> Dict[str, int]:
        return {rid: i for i, rid in enumerate(self.camera_type_register_ids)}

    def camera_type_for_combo_index(self, index: int) -> str:
        ids = self.camera_type_register_ids
        if not ids:
            return DEFAULT_CAMERA_TYPE
        if 0 <= index < len(ids):
            return ids[index]
        return ids[0]


def default_tab_item():
    from ..tab_item_config import TabItemConfig

    return TabItemConfig(id="camera", title="Камера", widget="camera")
