"""Тесты RecipeManager и функций миграции format_v1_to_v2.

12 unit-тестов:
- test_list_empty
- test_save_and_list
- test_load_updates_active
- test_delete_active_resets_state
- test_duplicate
- test_duplicate_fails_if_source_missing
- test_duplicate_fails_if_target_exists
- test_state_proxy_updated_on_load
- test_migrate_v1_to_v2_basic
- test_migrate_v1_with_display_wires
- test_is_v1_recipe_true
- test_is_v1_recipe_false

Используется tmp_path fixture для изоляции файловой системы.
RecipeEngine создаётся с реальным TreeStore и временной директорией.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore
from multiprocess_framework.modules.state_store_module.recipes.recipe_engine import (
    RecipeEngine,
)

from multiprocess_prototype.recipes.manager import RecipeManager
from multiprocess_prototype.recipes.migrations.format_v1_to_v2 import (
    is_v1_recipe,
    migrate_v1_to_v2,
)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def store() -> TreeStore:
    """Минимальный TreeStore для RecipeEngine."""
    return TreeStore({"cameras": {}, "renderer": {}})


@pytest.fixture
def recipes_dir(tmp_path: Path) -> Path:
    """Временная директория для рецептов."""
    d = tmp_path / "recipes"
    d.mkdir()
    return d


@pytest.fixture
def engine(store: TreeStore, recipes_dir: Path) -> RecipeEngine:
    """RecipeEngine без миграций (для тестов базового CRUD)."""
    return RecipeEngine(store=store, recipes_dir=recipes_dir)


@pytest.fixture
def manager(engine: RecipeEngine) -> RecipeManager:
    """RecipeManager без state_proxy и logger."""
    return RecipeManager(engine=engine)


def _make_recipe_yaml(name: str = "test") -> dict:
    """Создать минимальный v2-рецепт в формате RecipeEngine."""
    return {
        "meta": {
            "name": name,
            "description": "",
            "version": 2,
            "created_at": "2026-05-25T00:00:00+00:00",
        },
        "data": {},
    }


def _save_recipe_file(recipes_dir: Path, slug: str, name: str | None = None) -> Path:
    """Сохранить рецепт напрямую в директорию (обход RecipeEngine)."""
    recipe = _make_recipe_yaml(name or slug)
    path = recipes_dir / f"{slug}.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(recipe, f, default_flow_style=False, allow_unicode=True)
    return path


# ------------------------------------------------------------------
# Тесты RecipeManager
# ------------------------------------------------------------------


class TestRecipeManagerList:
    """Тесты метода list()."""

    def test_list_empty(self, manager: RecipeManager) -> None:
        """Новый менеджер на пустой директории → list() возвращает []."""
        result = manager.list()
        assert result == []

    def test_save_and_list(self, manager: RecipeManager, engine: RecipeEngine) -> None:
        """save('cup_inspection') → list() содержит 'cup_inspection'."""
        # engine.save создаёт YAML через TreeStore snapshot
        engine.save("cup_inspection", paths=[])
        result = manager.list()
        assert "cup_inspection" in result


class TestRecipeManagerLoad:
    """Тесты метода load()."""

    def test_load_updates_active(self, manager: RecipeManager, engine: RecipeEngine, recipes_dir: Path) -> None:
        """После load('cup_inspection') → get_active() == 'cup_inspection'."""
        _save_recipe_file(recipes_dir, "cup_inspection")
        manager.load("cup_inspection")
        assert manager.get_active() == "cup_inspection"


class TestRecipeManagerDelete:
    """Тесты метода delete()."""

    def test_delete_active_resets_state(self, manager: RecipeManager, engine: RecipeEngine, recipes_dir: Path) -> None:
        """Удалить активный → get_active() is None."""
        _save_recipe_file(recipes_dir, "cup_inspection")
        manager.load("cup_inspection")
        assert manager.get_active() == "cup_inspection"

        manager.delete("cup_inspection")
        assert manager.get_active() is None


class TestRecipeManagerDuplicate:
    """Тесты метода duplicate()."""

    def test_duplicate(self, manager: RecipeManager, recipes_dir: Path) -> None:
        """duplicate('cup', 'bottle') → list() содержит оба."""
        _save_recipe_file(recipes_dir, "cup")
        result = manager.duplicate("cup", "bottle")
        assert result is True
        slugs = manager.list()
        assert "cup" in slugs
        assert "bottle" in slugs

    def test_duplicate_fails_if_source_missing(self, manager: RecipeManager) -> None:
        """Source не существует → False."""
        result = manager.duplicate("nonexistent_source", "new_slug")
        assert result is False

    def test_duplicate_fails_if_target_exists(self, manager: RecipeManager, recipes_dir: Path) -> None:
        """Target уже есть → False."""
        _save_recipe_file(recipes_dir, "cup")
        _save_recipe_file(recipes_dir, "bottle")
        result = manager.duplicate("cup", "bottle")
        assert result is False

    def test_duplicate_fails_on_empty_source_slug(self, manager: RecipeManager, recipes_dir: Path) -> None:
        """duplicate с пустым source_slug → False без исключения."""
        _save_recipe_file(recipes_dir, "cup")
        result = manager.duplicate("", "bottle")
        assert result is False


class TestRecipeManagerStateProxy:
    """Тесты интеграции с StateProxy."""

    def test_state_proxy_updated_on_load(self, engine: RecipeEngine, recipes_dir: Path) -> None:
        """Mock StateProxy: set('recipes.active', 'cup_inspection') вызывается при load()."""
        mock_proxy = MagicMock()
        manager = RecipeManager(engine=engine, state_proxy=mock_proxy)

        _save_recipe_file(recipes_dir, "cup_inspection")
        manager.load("cup_inspection")

        mock_proxy.set.assert_called_with("recipes.active", "cup_inspection")


# ------------------------------------------------------------------
# Тесты функций миграции
# ------------------------------------------------------------------


class TestMigrateV1toV2:
    """Тесты функции migrate_v1_to_v2."""

    def test_migrate_v1_to_v2_basic(self) -> None:
        """Dict с topology → v2 dict с blueprint."""
        v1_data = {
            "name": "cup_inspection",
            "description": "Тест рецепт",
            "topology": {
                "processes": [{"process_name": "worker_1", "class": "Worker", "plugins": []}],
                "wires": [],
            },
        }

        result = migrate_v1_to_v2(v1_data)

        assert result["version"] == 2
        assert result["name"] == "cup_inspection"
        assert result["description"] == "Тест рецепт"
        assert "blueprint" in result
        assert "processes" in result["blueprint"]
        assert len(result["blueprint"]["processes"]) == 1
        assert result["blueprint"]["processes"][0]["process_name"] == "worker_1"

    def test_migrate_v1_with_display_wires(self) -> None:
        """Wire с target *.display.* попадает в display_bindings."""
        v1_data = {
            "name": "inspection",
            "description": "",
            "topology": {
                "processes": [],
                "wires": [
                    {
                        "source": "capture_proc.resize.out",
                        "target": "render.display.main_output",
                    },
                    {
                        "source": "merge_proc.out",
                        "target": "some.other.component",
                    },
                ],
            },
        }

        result = migrate_v1_to_v2(v1_data)

        assert len(result["display_bindings"]) == 1
        binding = result["display_bindings"][0]
        assert binding["source"] == "capture_proc.resize.out"
        # display — последний сегмент target
        assert binding["display"] == "main_output"

    def test_migrate_v1_missing_topology_graceful(self) -> None:
        """Dict без topology → graceful fallback, не исключение."""
        v1_data = {"name": "minimal", "description": ""}
        result = migrate_v1_to_v2(v1_data)

        assert result["version"] == 2
        assert result["blueprint"] == {"processes": [], "wires": []}
        assert result["active_services"] == []
        assert result["display_bindings"] == []


class TestIsV1Recipe:
    """Тесты функции is_v1_recipe."""

    def test_is_v1_recipe_true_no_version(self) -> None:
        """Dict без version → True."""
        data = {"name": "old_recipe", "topology": {}}
        assert is_v1_recipe(data) is True

    def test_is_v1_recipe_true_version_1(self) -> None:
        """Dict с version=1 → True."""
        data = {"version": 1, "name": "old"}
        assert is_v1_recipe(data) is True

    def test_is_v1_recipe_false_version_2(self) -> None:
        """Dict с version=2 → False."""
        data = {"version": 2, "blueprint": {}}
        assert is_v1_recipe(data) is False

    def test_is_v1_recipe_false_for_none(self) -> None:
        """None → False (без исключений)."""
        assert is_v1_recipe(None) is False

    def test_is_v1_recipe_false_for_non_dict(self) -> None:
        """Не-dict → False (без исключений)."""
        assert is_v1_recipe("string") is False
        assert is_v1_recipe(42) is False
        assert is_v1_recipe([]) is False


# ------------------------------------------------------------------
# Тест интеграции: RecipeEngine с migration_fn
# ------------------------------------------------------------------


class TestRecipeEngineWithMigration:
    """Тест что RecipeEngine корректно использует migrate_v1_to_v2 + is_v1_recipe."""

    def test_engine_uses_migration_fn(self, store: TreeStore, recipes_dir: Path) -> None:
        """RecipeEngine инициализируется с migration_fn → при load legacy-файла вызывается миграция."""
        # Создаём legacy YAML (v1-формат рецепта в секции data)
        legacy_recipe = {
            "meta": {"name": "old_recipe", "version": 1},
            "data": {
                # v1-данные: словарь, который is_v1_recipe проверяет как data
                "name": "old_recipe",
                "topology": {
                    "processes": [{"process_name": "cam_0"}],
                    "wires": [],
                },
            },
        }
        recipe_path = recipes_dir / "old_recipe.yaml"
        with open(recipe_path, "w", encoding="utf-8") as f:
            yaml.dump(legacy_recipe, f, default_flow_style=False, allow_unicode=True)

        # Инициализируем RecipeEngine с нашими функциями миграции
        engine_with_migration = RecipeEngine(
            store=store,
            recipes_dir=recipes_dir,
            migration_fn=migrate_v1_to_v2,
            migration_check_fn=is_v1_recipe,
            recipe_version=2,
        )

        # После load должен быть создан .bak файл
        engine_with_migration.load("old_recipe")

        bak_path = recipe_path.with_suffix(".yaml.bak")
        assert bak_path.exists(), "Backup .bak должен быть создан при миграции"
