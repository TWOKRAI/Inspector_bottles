"""Smoke-тесты для доменного wrapper RecipeEngine (Task 0.5).

Проверяет:
1. Импорт и наследование от framework-класса.
2. needs_migration корректно обнаруживает legacy-формат.
"""

from __future__ import annotations

from multiprocess_prototype.backend.state.recipes import RecipeEngine
from multiprocess_prototype.backend.state.recipes.migrations.v1_to_v2 import (
    migrate_recipe_data,
    needs_migration,
)
from multiprocess_framework.modules.state_store_module.recipes.recipe_engine import (
    RecipeEngine as FrameworkRecipeEngine,
)


def test_recipe_engine_is_subclass():
    """Доменный RecipeEngine наследует framework-класс (не дублирует логику)."""
    assert issubclass(RecipeEngine, FrameworkRecipeEngine)


def test_needs_migration_detects_processing_blocks():
    """needs_migration возвращает True при наличии processing_blocks в регионе."""
    recipe_data = {
        "cameras": {
            "0": {"regions": {"r0": {"processing_blocks": {"b0": {"enabled": True, "params": {"type": "gray"}}}}}}
        }
    }
    assert needs_migration(recipe_data) is True


def test_needs_migration_false_without_processing_blocks():
    """needs_migration возвращает False при отсутствии processing_blocks."""
    recipe_data = {
        "cameras": {
            "0": {
                "regions": {
                    "r0": {
                        "nodes": {
                            "n0": {
                                "node_id": "n0",
                                "operation_ref": "gray",
                                "enabled": True,
                            }
                        }
                    }
                }
            }
        }
    }
    assert needs_migration(recipe_data) is False


def test_migrate_recipe_data_converts_blocks_to_nodes():
    """migrate_recipe_data конвертирует processing_blocks → nodes."""
    recipe_data = {
        "cameras": {
            "0": {"regions": {"r0": {"processing_blocks": {"b0": {"enabled": True, "params": {"type": "gray"}}}}}}
        }
    }
    result = migrate_recipe_data(recipe_data)
    region = result["cameras"]["0"]["regions"]["r0"]
    assert "nodes" in region
    assert "processing_blocks" not in region
    assert region["nodes"]["b0"]["operation_ref"] == "gray"
    assert region["nodes"]["b0"]["enabled"] is True
