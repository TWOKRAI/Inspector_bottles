"""line_sim — объект-агностичный движок сцены «лента с объектами».

Публичный API (numpy/opencv/pydantic/yaml, без torch и PySide6):
    ObjectPassport, LayerSpec, LayerAugment, LayeredObject, ObjectFactory, ObjectSpawner,
    ScenePreset, SceneCompositor, SceneCompositorProtocol, encoder_to_offset_mm, FACTOR_MM,
    BELT_UX, BELT_UY
"""

from Services.line_sim.core import (
    BELT_UX,
    BELT_UY,
    FACTOR_MM,
    LayeredObject,
    ObjectFactory,
    ObjectSpawner,
    SceneCompositor,
    ScenePreset,
    encoder_to_offset_mm,
)
from Services.line_sim.interfaces import LayerAugment, LayerSpec, ObjectPassport, SceneCompositorProtocol

__all__ = [
    "BELT_UX",
    "BELT_UY",
    "FACTOR_MM",
    "LayerAugment",
    "LayerSpec",
    "LayeredObject",
    "ObjectFactory",
    "ObjectPassport",
    "ObjectSpawner",
    "SceneCompositor",
    "SceneCompositorProtocol",
    "ScenePreset",
    "encoder_to_offset_mm",
]
