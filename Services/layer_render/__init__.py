# -*- coding: utf-8 -*-
"""`layer_render` — стек слоёв фона для сцены (Task 1.1), геометрия/композиция и Windows-safe I/O (Task 2.1),
фотометрические эффекты (Task 2.2).

Контракт — в README.md.
"""

from Services.layer_render.background import (
    background_layers_from_config,
    fold_background,
    render_background,
)
from Services.layer_render.compose import (
    cast_contact_shadow,
    composite,
    crop_to_alpha,
    fit_longest_side,
    rotate_expand,
)
from Services.layer_render.crop import resize_square, side_from_radius, square_crop
from Services.layer_render.effects import EFFECT_PARAMS, EFFECTS, EffectSpec, apply_effects
from Services.layer_render.interfaces import ScrollingTile, SolidFill
from Services.layer_render.io import imread_unicode, imwrite_unicode

__all__ = [
    "EFFECTS",
    "EFFECT_PARAMS",
    "EffectSpec",
    "ScrollingTile",
    "SolidFill",
    "apply_effects",
    "background_layers_from_config",
    "cast_contact_shadow",
    "composite",
    "crop_to_alpha",
    "fit_longest_side",
    "fold_background",
    "imread_unicode",
    "imwrite_unicode",
    "render_background",
    "resize_square",
    "rotate_expand",
    "side_from_radius",
    "square_crop",
]
