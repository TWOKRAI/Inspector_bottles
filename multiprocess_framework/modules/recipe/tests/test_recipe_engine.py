"""Тесты RecipeEngine — snapshot/restore config-ветвей через TreeStore."""

from __future__ import annotations

import yaml
import pytest
from pathlib import Path

from multiprocess_framework.modules.recipe.recipe_engine import (
    RecipeEngine,
    _flatten,
    _remap_path,
)
from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore

# Доменные ветви инжектируются в движок (ADR-RCP-001) — раньше это была зашитая
# framework-константа DEFAULT_CONFIG_PATHS; теперь фикстура передаёт их явно.
_DEFAULT_CONFIG_PATHS = ["cameras", "renderer", "robot", "database"]


@pytest.fixture
def store() -> TreeStore:
    """TreeStore с типичными config-данными."""
    return TreeStore(
        {
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
        }
    )


@pytest.fixture
def recipes_dir(tmp_path: Path) -> Path:
    """Временная директория для рецептов."""
    d = tmp_path / "recipes"
    d.mkdir()
    return d


@pytest.fixture
def engine(store: TreeStore, recipes_dir: Path) -> RecipeEngine:
    """RecipeEngine с готовым store и временной директорией (доменные пути инжектированы)."""
    return RecipeEngine(
        store=store,
        recipes_dir=recipes_dir,
        default_paths=_DEFAULT_CONFIG_PATHS,
    )


# =====================================================================
# save — базовый
# =====================================================================


class TestSave:
    """Тесты сохранения рецептов."""

    def test_save_default_paths(self, engine: RecipeEngine, recipes_dir: Path) -> None:
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

    def test_save_partial_paths(self, engine: RecipeEngine, recipes_dir: Path) -> None:
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

    def test_save_nonexistent_path_skipped(self, engine: RecipeEngine, recipes_dir: Path) -> None:
        """save(paths=["nonexistent"]) → пустые данные (без ошибки)."""
        engine.save("empty", paths=["nonexistent"])

        file_path = recipes_dir / "empty.yaml"
        with open(file_path, "r", encoding="utf-8") as f:
            recipe = yaml.safe_load(f)

        assert recipe["data"] == {}

    def test_save_overwrites_existing(self, engine: RecipeEngine, recipes_dir: Path) -> None:
        """Повторный save перезаписывает файл."""
        engine.save("test")
        engine.save("test")  # перезапись
        assert (recipes_dir / "test.yaml").exists()


# =====================================================================
# load — базовый + Transaction batching
# =====================================================================


class TestLoad:
    """Тесты загрузки рецептов."""

    def test_load_applies_to_store(self, store: TreeStore, engine: RecipeEngine) -> None:
        """load() применяет рецепт к store через Transaction."""
        engine.save("prod")

        # Меняем store
        store.set("cameras.0.config.fps", 60, source="test")

        # Загружаем рецепт — должен вернуть fps обратно на 30
        deltas = engine.load("prod")

        assert len(deltas) > 0
        assert store.get("cameras.0.config.fps") == 30

    def test_load_returns_deltas_with_same_transaction_id(self, engine: RecipeEngine) -> None:
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

    def test_remap_camera_paths(self, store: TreeStore, engine: RecipeEngine) -> None:
        """remap={"cameras.0": "cameras.1"} → настройки камеры 0 в камеру 1."""
        # Сохраняем только камеру 0
        engine.save("cam0", paths=["cameras.0"])

        # Загружаем с ремаппингом в камеру 1
        _deltas = engine.load("cam0", remap={"cameras.0": "cameras.1"})

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

    def test_delete_existing(self, engine: RecipeEngine, recipes_dir: Path) -> None:
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
# set_active — чистый указатель (без TreeStore-replay)
# =====================================================================


class TestSetActive:
    """Тесты set_active() — только указатель, без config-side-effect."""

    def test_set_active_sets_pointer(self, engine: RecipeEngine) -> None:
        """set_active() устанавливает get_active() без вызова load()."""
        engine.save("prod")
        assert engine.get_active() is None

        result = engine.set_active("prod")
        assert result is True
        assert engine.get_active() == "prod"

    def test_set_active_nonexistent_returns_false(self, engine: RecipeEngine) -> None:
        """set_active() для несуществующего рецепта → False, указатель не меняется."""
        result = engine.set_active("nonexistent")
        assert result is False
        assert engine.get_active() is None

    def test_set_active_does_not_touch_tree_store(self, store: TreeStore, engine: RecipeEngine) -> None:
        """set_active() НЕ применяет data к TreeStore (ключевой acceptance).

        Сценарий: save → изменить store → set_active → store не восстановлен.
        В отличие от load(), который бы восстановил значения.
        """
        engine.save("prod")

        # Меняем store после save
        store.set("cameras.0.config.fps", 999, source="test")
        assert store.get("cameras.0.config.fps") == 999

        # set_active — только указатель
        result = engine.set_active("prod")
        assert result is True
        assert engine.get_active() == "prod"

        # TreeStore НЕ восстановлен (значение осталось 999, а не 30)
        assert store.get("cameras.0.config.fps") == 999

    def test_set_active_resets_snapshot(self, engine: RecipeEngine) -> None:
        """set_active() сбрасывает loaded_snapshot → is_dirty() = False."""
        engine.save("prod")
        engine.set_active("prod")
        # Без snapshot is_dirty всегда False
        assert engine.is_dirty() is False

    def test_set_active_overwrites_previous(self, engine: RecipeEngine) -> None:
        """Повторный set_active меняет указатель."""
        engine.save("alpha")
        engine.save("beta")

        engine.set_active("alpha")
        assert engine.get_active() == "alpha"

        engine.set_active("beta")
        assert engine.get_active() == "beta"


# =====================================================================
# deactivate
# =====================================================================


class TestDeactivate:
    """Тесты public deactivate() (симметрично set_active/load)."""

    def test_deactivate_resets_active(self, engine: RecipeEngine) -> None:
        """deactivate() сбрасывает get_active() в None."""
        engine.save("prod")
        engine.load("prod")
        assert engine.get_active() == "prod"

        engine.deactivate()
        assert engine.get_active() is None

    def test_deactivate_idempotent(self, engine: RecipeEngine) -> None:
        """deactivate() без активного рецепта — no-op (без ошибки)."""
        assert engine.get_active() is None
        engine.deactivate()
        assert engine.get_active() is None

    def test_not_dirty_after_deactivate(self, store: TreeStore, engine: RecipeEngine) -> None:
        """После deactivate() is_dirty() = False (snapshot сброшен)."""
        engine.save("prod")
        engine.load("prod")
        store.set("cameras.0.config.fps", 999, source="test")
        assert engine.is_dirty() is True

        engine.deactivate()
        assert engine.is_dirty() is False


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

    def test_dirty_after_change(self, store: TreeStore, engine: RecipeEngine) -> None:
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

    def test_diff_no_changes(self, engine: RecipeEngine) -> None:
        """diff() без изменений → пустой список."""
        engine.save("prod")
        diffs = engine.diff("prod")
        assert diffs == []

    def test_diff_shows_changes(self, store: TreeStore, engine: RecipeEngine) -> None:
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


# =====================================================================
# doc_type — дефолтная миграция через реестр run_chain (C3, ADR-RCP-003)
# =====================================================================

from multiprocess_framework.modules.recipe.migrations import migration  # noqa: E402

# Синтетический doc_type — изолирован от реальных (recipe.config_snapshot /
# recipe.file_format), чтобы тест не зависел от глобального реестра.
_TEST_DOC_TYPE = "test.engine_default_chain"


@migration(_TEST_DOC_TYPE, from_=1, to=2)
def _bump_marker_v1_to_v2(data: dict) -> dict:
    result = dict(data)
    result["migrated"] = True
    return result


class TestDocTypeDefaultMigration:
    """load() без migration_fn мигрирует устаревший рецепт через реестр по doc_type."""

    def test_doc_type_property_exposed(self, recipes_dir: Path) -> None:
        engine = RecipeEngine(store=TreeStore(), recipes_dir=recipes_dir, doc_type=_TEST_DOC_TYPE)
        assert engine.doc_type == _TEST_DOC_TYPE

    def test_doc_type_default_none(self, recipes_dir: Path) -> None:
        engine = RecipeEngine(store=TreeStore(), recipes_dir=recipes_dir)
        assert engine.doc_type is None

    def test_run_chain_default_migrates_outdated(self, recipes_dir: Path) -> None:
        # given v1-рецепт (envelope), движок с doc_type и БЕЗ migration_fn
        store = TreeStore({"cameras": {}})
        engine = RecipeEngine(
            store=store,
            recipes_dir=recipes_dir,
            recipe_version=2,
            doc_type=_TEST_DOC_TYPE,
        )
        path = recipes_dir / "old.yaml"
        recipe = {"meta": {"name": "old", "version": 1}, "data": {"cameras": {}}}
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(recipe, f, allow_unicode=True)

        # when грузим
        engine.load("old")

        # then файл перезаписан: run_chain применён (marker), meta.version bump до 2
        reloaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert reloaded["data"]["migrated"] is True
        assert reloaded["meta"]["version"] == 2
        assert reloaded["meta"]["migrated_from_v1"] is True

    def test_explicit_migration_fn_wins_over_registry(self, recipes_dir: Path) -> None:
        # given явный migration_fn — он приоритетнее дефолта run_chain по doc_type
        store = TreeStore({"cameras": {}})
        engine = RecipeEngine(
            store=store,
            recipes_dir=recipes_dir,
            recipe_version=2,
            doc_type=_TEST_DOC_TYPE,
            migration_fn=lambda d: {"explicit": True},
        )
        path = recipes_dir / "old.yaml"
        recipe = {"meta": {"name": "old", "version": 1}, "data": {"cameras": {}}}
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(recipe, f, allow_unicode=True)

        engine.load("old")

        reloaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        # применён явный migration_fn (explicit), НЕ реестровый marker
        assert reloaded["data"] == {"explicit": True}
        assert "migrated" not in reloaded["data"]

    def test_no_doc_type_no_default_migration(self, recipes_dir: Path) -> None:
        # given устаревший рецепт, движок без doc_type и без migration_fn
        store = TreeStore({"cameras": {}})
        engine = RecipeEngine(store=store, recipes_dir=recipes_dir, recipe_version=2)
        path = recipes_dir / "old.yaml"
        recipe = {"meta": {"name": "old", "version": 1}, "data": {"cameras": {"0": {"config": {"fps": 30}}}}}
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(recipe, f, allow_unicode=True)

        engine.load("old")

        # миграция не выполнена — файл не тронут (нет ни migration_fn, ни doc_type)
        reloaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert reloaded["meta"]["version"] == 1
        assert "migrated_from_v1" not in reloaded["meta"]
