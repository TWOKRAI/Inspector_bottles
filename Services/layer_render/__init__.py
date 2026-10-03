# -*- coding: utf-8 -*-
"""`layer_render` — стек слоёв фона для сцены (Task 1.1), геометрия/композиция и Windows-safe I/O (Task 2.1),
фотометрические эффекты (Task 2.2), стек слоёв объекта (Task 2.3), пресет сцены и каталог классов (Task 2.4a),
фабрика объекта и превью (Task 2.4b).

Контракт — в README.md.
"""

from Services.layer_render.background import (
    background_layers_from_config,
    fold_background,
    render_background,
)
from Services.layer_render.catalog import CatalogConfig, ClassEntry, SpriteCatalog, load_catalog
from Services.layer_render.compose import (
    cast_contact_shadow,
    composite,
    crop_to_alpha,
    fit_longest_side,
    rotate_expand,
)
from Services.layer_render.crop import resize_square, side_from_radius, square_crop
from Services.layer_render.effects import EFFECT_PARAMS, EFFECTS, EffectSpec, apply_effects
from Services.layer_render.factory import ObjectFactory, RenderedObject
from Services.layer_render.interfaces import ScrollingTile, SolidFill
from Services.layer_render.io import imread_unicode, imwrite_unicode, load_image_rgba
from Services.layer_render.layers import (
    AUGMENT_FIELDS,
    ComposedLayers,
    LayerAugment,
    LayerMode,
    LayerSpec,
    RangeF,
    SpriteSource,
    canvas_size,
    compose_layers,
    json_safe,
    load_layer_sprite,
    transform_layer,
)
from Services.layer_render.metadata import ClassMeta, SymmetryType, load_meta, write_meta
from Services.layer_render.preset import CLASS_SPRITE_SOURCE, ScenePreset
from Services.layer_render.preview import (
    OUTSIDE_ROOTS_MESSAGE,
    PreviewLimitError,
    confine_preset_paths,
    render_layout,
    render_preview_grid,
    validate_preview_request,
)
from Services.layer_render.procedural_backgrounds import procedural_background

__all__ = [
    "AUGMENT_FIELDS",
    "CLASS_SPRITE_SOURCE",
    "CatalogConfig",
    "ClassEntry",
    "ClassMeta",
    "ComposedLayers",
    "EFFECTS",
    "EFFECT_PARAMS",
    "EffectSpec",
    "LayerAugment",
    "LayerMode",
    "LayerSpec",
    "OUTSIDE_ROOTS_MESSAGE",
    "ObjectFactory",
    "PreviewLimitError",
    "RangeF",
    "RenderedObject",
    "ScrollingTile",
    "ScenePreset",
    "SolidFill",
    "SpriteCatalog",
    "SpriteSource",
    "SymmetryType",
    "apply_effects",
    "background_layers_from_config",
    "canvas_size",
    "cast_contact_shadow",
    "compose_layers",
    "confine_preset_paths",
    "composite",
    "crop_to_alpha",
    "fit_longest_side",
    "fold_background",
    "imread_unicode",
    "imwrite_unicode",
    "json_safe",
    "load_catalog",
    "load_image_rgba",
    "load_layer_sprite",
    "load_meta",
    "procedural_background",
    "render_background",
    "render_layout",
    "render_preview_grid",
    "resize_square",
    "rotate_expand",
    "side_from_radius",
    "square_crop",
    "transform_layer",
    "validate_preview_request",
    "write_meta",
]
