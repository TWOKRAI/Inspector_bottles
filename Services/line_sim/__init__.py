"""line_sim — объект-агностичный движок сцены «лента с объектами».

Публичный API (numpy/opencv/pydantic/yaml, без torch и PySide6):
    ObjectPassport, LayerSpec, LayerAugment, LayeredObject, ObjectFactory, ObjectSpawner,
    ScenePreset, SceneCompositor, SceneCompositorProtocol, encoder_to_offset_mm, FACTOR_MM,
    BELT_UX, BELT_UY, CLASS_SPRITE_SOURCE, render_preview_grid, validate_preview_request,
    confine_preset_paths, PreviewLimitError
"""

from Services.line_sim.core import (
    BELT_UX,
    BELT_UY,
    FACTOR_MM,
    LayeredObject,
    ObjectFactory,
    ObjectSpawner,
    SceneCompositor,
    PreviewLimitError,
    ScenePreset,
    confine_preset_paths,
    encoder_to_offset_mm,
    render_preview_grid,
    validate_preview_request,
)
from Services.line_sim.core.preset import CLASS_SPRITE_SOURCE
from Services.line_sim.interfaces import LayerAugment, LayerSpec, ObjectPassport, SceneCompositorProtocol

__all__ = [
    "BELT_UX",
    "BELT_UY",
    "CLASS_SPRITE_SOURCE",
    "FACTOR_MM",
    "LayerAugment",
    "LayerSpec",
    "LayeredObject",
    "ObjectFactory",
    "ObjectPassport",
    "ObjectSpawner",
    "SceneCompositor",
    "SceneCompositorProtocol",
    "PreviewLimitError",
    "ScenePreset",
    "confine_preset_paths",
    "encoder_to_offset_mm",
    "render_preview_grid",
    "validate_preview_request",
]
