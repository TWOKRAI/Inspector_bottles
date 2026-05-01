"""Тесты RecipeAdapter — тонкий адаптер RecipeManagerProtocol → RecipeEngine.

Проверяет:
- list_slots() делегирует в RecipeEngine.list()
- get_slot() читает данные из YAML-файла рецепта
- save_slot(name, data) записывает данные напрямую в YAML
- save_slot(name, data=None) делает snapshot через RecipeEngine.save()
- delete_slot() делегирует в RecipeEngine.delete()
- Формат YAML совместим между RecipeEngine и RecipeAdapter
"""
from __future__ import annotations

import pytest
import yaml
from pathlib import Path
from typing import Any, Dict

from multiprocess_framework.modules.state_store_module import TreeStore
from multiprocess_prototype.state_store.recipes.recipe_engine import RecipeEngine
from multiprocess_prototype.state_store.adapters.recipe_adapter import RecipeAdapter


# =====================================================================
# Фикстуры
# =====================================================================

@pytest.fixture
def store() -> TreeStore:
    """TreeStore с типичными config-данными."""
    return TreeStore({
        "cameras": {
            "0": {
                "config": {
                    "fps": 30,
                    "camera_type": "webcam",
                },
            },
        },
        "renderer": {
            "config": {
                "draw_bboxes": True,
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


@pytest.fixture
def adapter(engine: RecipeEngine) -> RecipeAdapter:
    """RecipeAdapter обёрнутый над RecipeEngine."""
    return RecipeAdapter(recipe_engine=engine)


# =====================================================================
# Тест 1: list_slots — делегирует в engine.list()
# =====================================================================

class TestListSlots:
    def test_list_empty(self, adapter: RecipeAdapter) -> None:
        """list_slots() на пустой директории → пустой список."""
        assert adapter.list_slots() == []

    def test_list_returns_saved_slots(
        self, adapter: RecipeAdapter, engine: RecipeEngine
    ) -> None:
        """list_slots() возвращает имена сохранённых рецептов."""
        engine.save("alpha")
        engine.save("beta")

        slots = adapter.list_slots()
        assert slots == ["alpha", "beta"]

    def test_list_reflects_adapter_saves(self, adapter: RecipeAdapter) -> None:
        """list_slots() отражает рецепты сохранённые через adapter.save_slot()."""
        sample_data = {"cameras": {"0": {"config": {"fps": 25}}}}
        adapter.save_slot("slot_a", sample_data)
        adapter.save_slot("slot_b", sample_data)

        slots = adapter.list_slots()
        assert "slot_a" in slots
        assert "slot_b" in slots


# =====================================================================
# Тест 2: get_slot — читает данные из YAML
# =====================================================================

class TestGetSlot:
    def test_get_nonexistent_returns_none(self, adapter: RecipeAdapter) -> None:
        """get_slot() несуществующего рецепта → None."""
        result = adapter.get_slot("nonexistent")
        assert result is None

    def test_get_slot_after_save_with_data(self, adapter: RecipeAdapter) -> None:
        """get_slot() возвращает данные, записанные через save_slot(name, data)."""
        data = {"cameras": {"0": {"config": {"fps": 60}}}}
        adapter.save_slot("prod", data)

        result = adapter.get_slot("prod")
        assert result is not None
        assert result["cameras"]["0"]["config"]["fps"] == 60

    def test_get_slot_returns_deep_copy(self, adapter: RecipeAdapter) -> None:
        """get_slot() возвращает глубокую копию — мутация результата не влияет на хранилище."""
        data = {"cameras": {"0": {"config": {"fps": 30}}}}
        adapter.save_slot("test", data)

        result1 = adapter.get_slot("test")
        result1["cameras"]["0"]["config"]["fps"] = 999  # мутируем копию

        result2 = adapter.get_slot("test")
        assert result2["cameras"]["0"]["config"]["fps"] == 30


# =====================================================================
# Тест 3: save_slot с data — записывает напрямую в YAML
# =====================================================================

class TestSaveSlotWithData:
    def test_save_creates_yaml_file(
        self, adapter: RecipeAdapter, recipes_dir: Path
    ) -> None:
        """save_slot(name, data) создаёт YAML-файл в recipes_dir."""
        data = {"renderer": {"config": {"draw_bboxes": False}}}
        adapter.save_slot("my_recipe", data)

        file_path = recipes_dir / "my_recipe.yaml"
        assert file_path.exists()

    def test_save_yaml_has_meta_and_data(
        self, adapter: RecipeAdapter, recipes_dir: Path
    ) -> None:
        """YAML-файл имеет секции meta и data совместимые с RecipeEngine."""
        data = {"robot": {"config": {"speed": 50}}}
        adapter.save_slot("robot_slow", data)

        with open(recipes_dir / "robot_slow.yaml", "r", encoding="utf-8") as f:
            recipe = yaml.safe_load(f)

        assert "meta" in recipe
        assert recipe["meta"]["name"] == "robot_slow"
        assert "created_at" in recipe["meta"]
        assert recipe["data"]["robot"]["config"]["speed"] == 50

    def test_save_overwrites_existing(self, adapter: RecipeAdapter) -> None:
        """Повторный save_slot перезаписывает предыдущее значение."""
        adapter.save_slot("slot1", {"cameras": {"0": {"config": {"fps": 30}}}})
        adapter.save_slot("slot1", {"cameras": {"0": {"config": {"fps": 60}}}})

        result = adapter.get_slot("slot1")
        assert result["cameras"]["0"]["config"]["fps"] == 60


# =====================================================================
# Тест 4: save_slot без data — snapshot через RecipeEngine
# =====================================================================

class TestSaveSlotSnapshot:
    def test_save_without_data_snapshots_store(
        self, adapter: RecipeAdapter, store: TreeStore, recipes_dir: Path
    ) -> None:
        """save_slot(name) без data → snapshot текущего store через RecipeEngine."""
        adapter.save_slot("current")

        file_path = recipes_dir / "current.yaml"
        assert file_path.exists()

    def test_save_without_data_captures_store_values(
        self, adapter: RecipeAdapter, store: TreeStore
    ) -> None:
        """Snapshot содержит текущие значения из store."""
        # Меняем store
        store.set("cameras.0.config.fps", 25, source="test")

        adapter.save_slot("snap")

        result = adapter.get_slot("snap")
        assert result is not None
        # Данные должны прийти из store
        # RecipeEngine snapshot захватывает DEFAULT_CONFIG_PATHS
        assert "cameras" in result


# =====================================================================
# Тест 5: delete_slot — делегирует в engine.delete()
# =====================================================================

class TestDeleteSlot:
    def test_delete_existing(
        self, adapter: RecipeAdapter, recipes_dir: Path
    ) -> None:
        """delete_slot() удаляет файл и возвращает True."""
        data = {"renderer": {"config": {"draw_bboxes": True}}}
        adapter.save_slot("to_delete", data)
        assert (recipes_dir / "to_delete.yaml").exists()

        result = adapter.delete_slot("to_delete")
        assert result is True
        assert not (recipes_dir / "to_delete.yaml").exists()

    def test_delete_nonexistent(self, adapter: RecipeAdapter) -> None:
        """delete_slot() несуществующего → False."""
        result = adapter.delete_slot("nonexistent")
        assert result is False

    def test_delete_removes_from_list(self, adapter: RecipeAdapter) -> None:
        """После delete_slot() рецепт исчезает из list_slots()."""
        data = {"cameras": {"0": {"config": {"fps": 15}}}}
        adapter.save_slot("temp", data)
        assert "temp" in adapter.list_slots()

        adapter.delete_slot("temp")
        assert "temp" not in adapter.list_slots()


# =====================================================================
# Тест 6: совместимость формата — RecipeEngine может загрузить
#         рецепт, сохранённый через RecipeAdapter
# =====================================================================

class TestFormatCompatibility:
    def test_engine_can_load_adapter_saved_recipe(
        self, adapter: RecipeAdapter, engine: RecipeEngine, store: TreeStore
    ) -> None:
        """RecipeEngine.load() успешно загружает рецепт, записанный adapter.save_slot()."""
        # Сохраняем рецепт через адаптер
        data = {
            "cameras": {
                "0": {
                    "config": {
                        "fps": 15,
                        "camera_type": "ip",
                    }
                }
            }
        }
        adapter.save_slot("compat_test", data)

        # Меняем store
        store.set("cameras.0.config.fps", 999, source="test")

        # Загружаем через RecipeEngine
        deltas = engine.load("compat_test")

        # Store должен обновиться значениями из рецепта
        assert store.get("cameras.0.config.fps") == 15
        assert store.get("cameras.0.config.camera_type") == "ip"
