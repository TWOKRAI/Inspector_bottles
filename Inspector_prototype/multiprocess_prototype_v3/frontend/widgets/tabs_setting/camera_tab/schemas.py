# multiprocess_prototype_v3/frontend/widgets/camera_tab/schemas.py
"""
Конфиг camera_tab: переключатель типа камеры (ComboBox).

Дочерние виджеты (simulator, webcam, hikvision) имеют собственные схемы.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import Field

from multiprocess_prototype_v3.camera_policy import (
    DEFAULT_CAMERA_TYPE,
    WEBCAM_ENUM_DEFAULT_MAX_INDEX,
    WEBCAM_ENUM_HARD_CAP,
)

from multiprocess_framework.modules.data_schema_module import (
    SchemaBase,
    register_schema,
)

from multiprocess_prototype_v3.frontend.widgets.hikvision_camera_mvp.schemas import (
    HikvisionCameraMvpUiConfig,
)


def _default_camera_type_ids() -> List[str]:
    """Идентификаторы типов камеры (ключи регистра / стека)."""
    from multiprocess_prototype_v3.camera_policy import CAMERA_TYPES
    return list(CAMERA_TYPES)


def _default_camera_type_labels() -> List[str]:
    """Подписи для QComboBox в том же порядке, что и camera_type_register_ids."""
    from multiprocess_prototype_v3.camera_policy import CAMERA_TYPE_LABELS
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
    # Секция UI Hikvision (MVP); dict из YAML приводится к модели при валидации CameraTabUiConfig.
    hikvision: HikvisionCameraMvpUiConfig = Field(default_factory=HikvisionCameraMvpUiConfig)

    touch_keyboard: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Touch-клавиатура для вкладки камеры (FPS, spinbox Hikvision); mode: mini | full.",
    )

    touch_keyboard_fps: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Перекрывает touch_keyboard для Sim/Webcam (FPS и др.); mode: mini | full.",
    )

    touch_keyboard_hikvision: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Перекрывает touch_keyboard для Hikvision; mode: mini | full.",
    )

    def camera_type_index_map(self) -> Dict[str, int]:
        """Маппинг camera_type → индекс в ComboBox/стеке."""
        return {rid: i for i, rid in enumerate(self.camera_type_register_ids)}

    def camera_type_for_combo_index(self, index: int) -> str:
        """Строковый id типа камеры по индексу ComboBox."""
        ids = self.camera_type_register_ids
        if not ids:
            return DEFAULT_CAMERA_TYPE
        if 0 <= index < len(ids):
            return ids[index]
        return ids[0]


def default_tab_item():
    """TabItemConfig вкладки «Камера»."""
    from ..tab_item_config import TabItemConfig

    return TabItemConfig(id="camera", title="Камера", widget="camera")
