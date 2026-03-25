# multiprocess_prototype/registers/snapshot_migrate.py
"""
Нормализация снимка register_recipes перед model_validate_all (YAML / старые форматы).

Дублирует логику ProcessorRegisters._normalize_nested_payloads для слоя I/O,
чтобы миграция была явной и расширяема без повторного открытия RecipeManager.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from .schemas.processing_tab.names import PROCESSOR_REGISTER
from .schemas.processing_tab.nested_payload import (
    DEFAULT_CROP_CAMERA_ID,
    normalize_crop_regions_payload,
    normalize_post_processing_payload,
)


def migrate_register_recipe_snapshot(data: Dict[str, Any]) -> Dict[str, Any]:
    """Deep copy + нормализация вложенных полей processor."""
    out: Dict[str, Any] = deepcopy(data)
    proc = out.get(PROCESSOR_REGISTER)
    if not isinstance(proc, dict):
        return out
    p = dict(proc)
    if "crop_regions" in p:
        p["crop_regions"] = normalize_crop_regions_payload(
            p["crop_regions"],
            default_camera=DEFAULT_CROP_CAMERA_ID,
        )
    if "post_processing_regions" in p:
        p["post_processing_regions"] = normalize_post_processing_payload(
            p["post_processing_regions"]
        )
    out[PROCESSOR_REGISTER] = p
    return out
