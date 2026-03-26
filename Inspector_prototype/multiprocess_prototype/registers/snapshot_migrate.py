# multiprocess_prototype/registers/snapshot_migrate.py
"""
Нормализация снимка register_recipes перед model_validate_all (YAML / старые форматы).

Миграция legacy ``crop_regions`` / ``post_processing_regions`` в ``vision_pipeline`` —
``normalize_processor_register_payload`` (см. pipeline.migration).
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from .schemas.pipeline.migration import normalize_processor_register_payload
from .schemas.processing_tab.names import PROCESSOR_REGISTER


def migrate_register_recipe_snapshot(data: Dict[str, Any]) -> Dict[str, Any]:
    """Deep copy + нормализация вложенных полей processor."""
    out: Dict[str, Any] = deepcopy(data)
    proc = out.get(PROCESSOR_REGISTER)
    if not isinstance(proc, dict):
        return out
    out[PROCESSOR_REGISTER] = normalize_processor_register_payload(dict(proc))
    return out
