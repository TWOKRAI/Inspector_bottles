# multiprocess_prototype/registers/snapshot_migrate.py
"""
Нормализация снимка ``register_recipes`` **до** вызова ``RegistersManager.model_validate_all``.

Граница приложения: миграции legacy YAML и переименования полей не входят в
``registers_module.RegistersManager`` — только сюда и в вызывающий код (см. ``RecipeManager``).
``normalize_processor_register_payload`` — см. ``schemas.pipeline.migration``.
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
