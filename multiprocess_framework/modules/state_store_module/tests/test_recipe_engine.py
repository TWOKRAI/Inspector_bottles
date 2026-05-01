"""Тесты RecipeEngine — snapshot/restore config-ветвей через TreeStore."""
from __future__ import annotations

import yaml
import pytest
from pathlib import Path

from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore
from multiprocess_framework.modules.state_store_module.core.delta import Delta
from multiprocess_framework.modules.state_store_module.recipes.recipe_engine import (
    RecipeEngine,
    DEFAULT_CONFIG_PATHS,
    _flatten,
    _remap_path,
)


@pytest.fixture
def store() -> TreeStore:
    """TreeStore с типичными config-данными."""
    return TreeStore({
        "cameras": {
            "0": {
                "config": {
                    "fps": 30,
                    "camera_type": "webcam",
                    "resolution_width": 1920,
                    "resolution_height": 1080,
                },
                "regions": {
                    "0": {
                        "name": "main",
                        "params": {"threshold": 128},
                    },
                },
                "state": {"status": "running"},
            },
            "1": {
                "config": {
                    "fps": 15,
                    "camera_type": "ip",
                },
            },
        },
        "renderer": {
            "config": {
                "draw_bboxes": True,
                "show_original": True,
            },
        },
        "robot": {
            "config": {
                "speed": 100,
                "enabled": False,
            },
        },
        "database": {
            "config": {
                "host": "localhost",
                "port": 5432,
            },
        },
    })


@pytest.fixture
def recipes_dir(tmp_path: Path) -> Path:
    """Временная директория для рецептов."""
    d = tmp_path / "recipes"
    d.mkdir()
    return d


@pytest.fixture
def engine(store: TreeStore, recipes_dir: Path) -> RecipeEngine:
    """RecipeEngine с готовым store и временной директорией."""
    return RecipeEngine(store=store, recipes_dir=recipes_dir)


# =====================================================================
# save — базовый
# =====================================================================

class TestSave:
    """Тесты сохранения рецептов."""

    def test_save_default_paths(
        self, engine: RecipeEngine, recipes_dir: Path
    ) -> None:
        """save() без paths → snapshot всех DEFAULT_CONFIG_PATHS."""
        engine.save("production")

        file_path = recipes_dir / "production.yaml"
        assert file_path.exists()

        with open(file_path, "r", encoding="utf-8") as f:
            recipe = yaml.safe_load(f)

        # Проверяем структуру meta
        assert recipe["meta"]["name"] == "production"
        assert "created_at" in recipe["meta"]

        # Проверяем что данные содержат ожидаемые ветви
        data = recipe["data"]
        assert "cameras" in data
        assert "renderer" in data
        assert "robot" in data
        assert "database" in data

        # Проверяем конкретные значения
        assert data["cameras"]["0"]["config"]["fps"] == 30
        assert data["renderer"]["config"]["draw_bboxes"] is True

    def test_save_partial_paths(
        self, engine: RecipeEngine, recipes_dir: Path
    ) -> None:
        """save(paths=["cameras.0.regions"]) → частичный snapshot."""
        engine.save("regions_only", paths=["cameras.0.regions"])

        file_path = recipes_dir / "regions_only.yaml"
        with open(file_path, "r", encoding="utf-8") as f:
            recipe = yaml.safe_load(f)

        data = recipe["data"]
        # Должны быть только regions камеры 0
        assert data["cameras"]["0"]["regions"]["0"]["name"] == "main"
        # Не должно быть config камеры 0
        assert "config" not in data["cameras"]["0"]
        # Не должно быть renderer, robot, database
        assert "renderer" not in data
        assert "robot" not in data

    def test_save_nonexistent_path_skipped(
        self, engine: RecipeEngine, recipes_dir: Path
    ) -> None:
        """save(paths=["nonexistent"]) → пустые данные (без ошибки)."""
        engine.save("empty", paths=["nonexistent"])

        file_path = recipes_dir / "empty.yaml"
        with open(file_path, "r", encoding="utf-8") as f:
            recipe = yaml.safe_load(f)

        assert recipe["data"] == {}

    def test_save_overwrites_existing(
        self, engine: RecipeEngine, recipes_dir: Path
    ) -> None:
        """Повторный save перезаписывает файл."""
        engine.save("test")
        engine.save("test")  # перезапись
        assert (recipes_dir / "test.yaml").exists()


# =====================================================================
# load — базовый + Transaction batching
# =====================================================================

class TestLoad:
    """Тесты загрузки рецептов."""

    def test_load_applies_to_store(
        self, store: TreeStore, engine: RecipeEngine
    ) -> None:
        """load() применяет рецепт к store через Transaction."""
        engine.save("prod")

        # Меняем store
        store.set("cameras.0.config.fps", 60, source="test")

        # Загружаем рецепт — должен вернуть fps обратно на 30
        deltas = engine.load("prod")

        assert len(deltas) > 0
        assert store.get("cameras.0.config.fps") == 30

    def test_load_returns_deltas_with_same_transaction_id(
        self, engine: RecipeEngine
    ) -> None:
        """Все дельты load() имеют одинаковый transaction_id (batching)."""
        engine.save("prod")
        # Изменяем несколько значений чтобы load вернул дельты
        engine._store.set("cameras.0.config.fps", 999, source="test")
        engine._store.set("renderer.config.draw_bboxes", False, source="test")

        deltas = engine.load("prod")

        assert len(deltas) >= 2
        tx_ids = {d.transaction_id for d in deltas}
        assert len(tx_ids) == 1, "Все дельты должны иметь один transaction_id"

    def test_load_nonexistent_raises(self, engine: RecipeEngine) -> None:
        """load() несуществующего рецепта → FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            engine.load("nonexistent")

    def test_load_sets_active(self, engine: RecipeEngine) -> None:
        """load() устанавливает active_name."""
        engine.save("prod")
        assert engine.get_active() is None

        engine.load("prod")
        assert engine.get_active() == "prod"


# =====================================================================
# remap
# =====================================================================

class TestRemap:
    """Тесты перемаппинга путей при загрузке."""

    def test_remap_camera_paths(
        self, store: TreeStore, engine: RecipeEngine
    ) -> None:
        """remap={"cameras.0": "cameras.1"} → настройки камеры 0 в камеру 1."""
        # Сохраняем только камеру 0
        engine.save("cam0", paths=["cameras.0"])

        # Загружаем с ремаппингом в камеру 1
        deltas = engine.load("cam0", remap={"cameras.0": "cameras.1"})

        # Камера 1 теперь должна иметь config от камеры 0
        assert store.get("cameras.1.config.fps") == 30
        assert store.get("cameras.1.config.camera_type") == "webcam"

    def test_remap_path_helper(self) -> None:
        """Проверяем функцию _remap_path напрямую."""
        remap = {"cameras.0": "cameras.1"}

        assert _remap_path("cameras.0.config.fps", remap) == "cameras.1.config.fps"
        assert _remap_path("cameras.0", remap) == "cameras.1"
        assert _remap_path("renderer.config", remap) == "renderer.config"

    def test_remap_longer_prefix_priority(self) -> None:
        """Длиннейший префикс имеет приоритет."""
        remap = {
            "cameras.0": "cameras.2",
            "cameras.0.regions": "cameras.3.regions",
        }
        result = _remap_path("cameras.0.regions.0.name", remap)
        assert result == "cameras.3.regions.0.name"


# =====================================================================
# list / delete
# =====================================================================

class TestListDelete:
    """Тесты list и delete."""

    def test_list_empty(self, engine: RecipeEngine) -> None:
        """list() на пустой директории → пустой список."""
        assert engine.list() == []

    def test_list_returns_names(self, engine: RecipeEngine) -> None:
        """list() возвращает имена рецептов (без .yaml)."""
        engine.save("alpha")
        engine.save("beta")

        names = engine.list()
        assert names == ["alpha", "beta"]

    def test_delete_existing(
        self, engine: RecipeEngine, recipes_dir: Path
    ) -> None:
        """delete() удаляет файл и возвращает True."""
        engine.save("to_delete")
        assert (recipes_dir / "to_delete.yaml").exists()

        result = engine.delete("to_delete")
        assert result is True
        assert not (recipes_dir / "to_delete.yaml").exists()

    def test_delete_nonexistent(self, engine: RecipeEngine) -> None:
        """delete() несуществующего рецепта → False."""
        result = engine.delete("nonexistent")
        assert result is False

    def test_delete_active_resets_active(self, engine: RecipeEngine) -> None:
        """Удаление активного рецепта сбрасывает get_active()."""
        engine.save("active_recipe")
        engine.load("active_recipe")
        assert engine.get_active() == "active_recipe"

        engine.delete("active_recipe")
        assert engine.get_active() is None


# =====================================================================
# is_dirty
# =====================================================================

class TestIsDirty:
    """Тесты отслеживания изменений после загрузки."""

    def test_not_dirty_after_load(self, engine: RecipeEngine) -> None:
        """Сразу после load() — is_dirty() = False."""
        engine.save("prod")
        engine.load("prod")
        assert engine.is_dirty() is False

    def test_dirty_after_change(
        self, store: TreeStore, engine: RecipeEngine
    ) -> None:
        """Изменение store после load() → is_dirty() = True."""
        engine.save("prod")
        engine.load("prod")

        store.set("cameras.0.config.fps", 999, source="test")
        assert engine.is_dirty() is True

    def test_not_dirty_without_load(self, engine: RecipeEngine) -> None:
        """Без load() — is_dirty() = False (нечего сравнивать)."""
        assert engine.is_dirty() is False


# =====================================================================
# diff
# =====================================================================

class TestDiff:
    """Тесты отображения различий между рецептом и store."""

    def test_diff_no_changes(
        self, engine: RecipeEngine
    ) -> None:
        """diff() без изменений → пустой список."""
        engine.save("prod")
        diffs = engine.diff("prod")
        assert diffs == []

    def test_diff_shows_changes(
        self, store: TreeStore, engine: RecipeEngine
    ) -> None:
        """diff() показывает изменённые пути."""
        engine.save("prod")

        # Меняем fps
        store.set("cameras.0.config.fps", 60, source="test")

        diffs = engine.diff("prod")
        # Должен быть хотя бы один diff для fps
        fps_diffs = [d for d in diffs if d[0] == "cameras.0.config.fps"]
        assert len(fps_diffs) == 1
        path, current, recipe = fps_diffs[0]
        assert current == 60
        assert recipe == 30

    def test_diff_nonexistent_raises(self, engine: RecipeEngine) -> None:
        """diff() несуществующего рецепта → FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            engine.diff("nonexistent")


# =====================================================================
# Вспомогательные функции
# =====================================================================

class TestHelpers:
    """Тесты вспомогательных функций."""

    def test_flatten_simple(self) -> None:
        """_flatten разворачивает nested dict."""
        data = {"a": {"b": 1, "c": 2}, "d": 3}
        result = dict(_flatten(data))
        assert result == {"a.b": 1, "a.c": 2, "d": 3}

    def test_flatten_deep(self) -> None:
        """_flatten с глубокой вложенностью."""
        data = {"x": {"y": {"z": 42}}}
        result = dict(_flatten(data))
        assert result == {"x.y.z": 42}
