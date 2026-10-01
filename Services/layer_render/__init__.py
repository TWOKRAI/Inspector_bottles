# -*- coding: utf-8 -*-
"""`layer_render` — стек слоёв фона для сцены (Task 1.1). Контракт — в README.md."""

from Services.layer_render.background import (
    background_layers_from_config,
    fold_background,
    render_background,
)
from Services.layer_render.interfaces import ScrollingTile, SolidFill

__all__ = [
    "ScrollingTile",
    "SolidFill",
    "background_layers_from_config",
    "fold_background",
    "render_background",
]
