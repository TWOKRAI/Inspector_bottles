"""line_sim — объект-агностичный движок сцены «лента с объектами».

Публичный API (numpy/opencv/pydantic/yaml, без torch и PySide6):
    ObjectPassport, LayerSpec, LayerAugment, LayeredObject, ObjectFactory, ScenePreset,
    SceneCompositor (Protocol), encoder_to_offset_mm, FACTOR_MM, BELT_UX, BELT_UY
"""

from Services.line_sim.core import (
    BELT_UX,
    BELT_UY,
    FACTOR_MM,
    LayeredObject,
    ObjectFactory,
    ScenePreset,
    encoder_to_offset_mm,
)
from Services.line_sim.interfaces import LayerAugment, LayerSpec, ObjectPassport, SceneCompositor

__all__ = [
    "BELT_UX",
    "BELT_UY",
    "FACTOR_MM",
    "LayerAugment",
    "LayerSpec",
    "LayeredObject",
    "ObjectFactory",
    "ObjectPassport",
    "SceneCompositor",
    "ScenePreset",
    "encoder_to_offset_mm",
]
