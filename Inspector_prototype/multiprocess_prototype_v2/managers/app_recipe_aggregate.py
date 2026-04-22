# multiprocess_prototype/managers/app_recipe_aggregate.py
"""
Агрегат схем для app_recipes: RecipesTabConfig + ProcessingTabUiConfig.

Импорты схем из frontend — только внутри функций (избегаем загрузки widgets/__init__
при import managers из тестов без frontend_module).
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Type

from multiprocess_framework.modules.data_schema_module import SchemaBase, get_default_registry


def _recipe_and_processing_schema_classes() -> tuple[Type[SchemaBase], Type[SchemaBase]]:
    from multiprocess_prototype_v2.frontend.widgets.processing_panel_widget.schemas import (
        ProcessingTabUiConfig,
    )
    from multiprocess_prototype_v2.frontend.widgets.settings_recipe_widget.schemas import RecipesTabConfig

    return (RecipesTabConfig, ProcessingTabUiConfig)


def app_recipe_schema_names() -> List[str]:
    return [cls.__name__ for cls in _recipe_and_processing_schema_classes()]


def build_default_app_aggregate(
    *,
    recipes_tab_dict: Dict[str, Any] | None = None,
    processing_tab_ui_dict: Dict[str, Any] | None = None,
) -> Dict[str, SchemaBase]:
    """Собрать агрегат по умолчанию; словари — из build_dict конфига."""
    RecipesTabConfig, ProcessingTabUiConfig = _recipe_and_processing_schema_classes()
    return {
        "RecipesTabConfig": RecipesTabConfig.model_validate(recipes_tab_dict or {}),
        "ProcessingTabUiConfig": ProcessingTabUiConfig.model_validate(processing_tab_ui_dict or {}),
    }


def aggregate_to_snapshot(aggregate: Dict[str, SchemaBase]) -> Dict[str, Any]:
    return {name: model.model_dump() for name, model in aggregate.items()}


def snapshot_to_aggregate(snapshot: Dict[str, Any]) -> Dict[str, SchemaBase]:
    """Восстановить агрегат из снимка; неизвестные ключи пропускаются."""
    registry = get_default_registry()
    out: Dict[str, SchemaBase] = {}
    for name, data in snapshot.items():
        if not isinstance(data, dict):
            continue
        cls = registry.get(name)
        if cls is None:
            continue
        try:
            out[name] = cls.model_validate(data)
        except Exception:
            continue
    return out


def merge_aggregate_with_defaults(snapshot: Dict[str, Any]) -> Dict[str, SchemaBase]:
    """Слить снимок с дефолтными экземплярами, чтобы не терять схемы при частичном YAML."""
    base = build_default_app_aggregate()
    merged = snapshot_to_aggregate(snapshot)
    for key, inst in base.items():
        if key not in merged:
            merged[key] = deepcopy(inst)
    return merged
