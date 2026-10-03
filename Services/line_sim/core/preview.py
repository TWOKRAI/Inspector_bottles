# -*- coding: utf-8 -*-
"""Превью пресета — реэкспорт из `Services.layer_render.preview` (Task 2.4b).

Код переехал в `layer_render`; этот модуль сохраняет старый путь импорта. Те же объекты (`is`).
Кэш фабрики превью (`_factory_cache`) — глобал `layer_render.preview`.
"""

from __future__ import annotations

from Services.layer_render.preview import (
    OUTSIDE_ROOTS_MESSAGE,
    PREVIEW_DEFAULT_SEEDS,
    PREVIEW_DEFAULT_TILE_PX,
    PREVIEW_MAX_SEEDS,
    PREVIEW_MAX_TILE_PX,
    PREVIEW_MIN_TILE_PX,
    PREVIEW_PIXEL_BUDGET,
    PreviewLimitError,
    confine_preset_paths,
    render_layout,
    render_preview_grid,
    validate_preview_request,
)

__all__ = [
    "OUTSIDE_ROOTS_MESSAGE",
    "PREVIEW_DEFAULT_SEEDS",
    "PREVIEW_DEFAULT_TILE_PX",
    "PREVIEW_MAX_SEEDS",
    "PREVIEW_MAX_TILE_PX",
    "PREVIEW_MIN_TILE_PX",
    "PREVIEW_PIXEL_BUDGET",
    "PreviewLimitError",
    "confine_preset_paths",
    "render_layout",
    "render_preview_grid",
    "validate_preview_request",
]
