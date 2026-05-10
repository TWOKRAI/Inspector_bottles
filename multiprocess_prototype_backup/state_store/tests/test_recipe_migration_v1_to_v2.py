"""Тесты миграции рецептов v1 → v2 (processing_blocks → nodes).

Покрывает:
1. Чистые функции migrate_recipe_data / needs_migration.
2. RecipeEngine.load() с legacy-рецептом (integration).
3. Round-trip Pipeline через ветку cameras (DAG save/load).
"""
from __future__ import annotations

import copy
import logging

import pytest
import yaml
from pathlib import Path

from multiprocess_framework.modules.state_store_module import TreeStore
from multiprocess_prototype.state_store.recipes.recipe_engine import RecipeEngine
from multiprocess_prototype.state_store.recipes.migrations import (
    RECIPE_VERSION_V1,
    RECIPE_VERSION_V2,
    migrate_recipe_data,
    needs_migration,
)


# =====================================================================
# Фикстуры
# =====================================================================


@pytest.fixture
def recipes_dir(tmp_path: Path) -> Path:
    """Временная директория для рецептов."""
    d = tmp_path / "recipes"
    d.mkdir()
    return d


@pytest.fixture
def empty_store() -> TreeStore:
    """Пустой TreeStore."""
    return TreeStore({})


@pytest.fixture
def engine(empty_store: TreeStore, recipes_dir: Path) -> RecipeEngine:
    """RecipeEngine с пустым store и временной директорией."""
    return RecipeEngine(store=empty_store, recipes_dir=recipes_dir)


def make_legacy_data(
    cam_id: str = "0",
    region_id: str = "r0",
    blocks: dict | None = None,
) -> dict:
    """Вспомогательная фабрика для legacy recipe_data."""
    if blocks is None:
        blocks = {
            "b0": {
                "enabled": True,
                "params": {"type": "color_detection", "color_lower": [0, 0, 0]},
            }
        }
    return {
        "cameras": {
            cam_id: {
                "regions": {
                    region_id: {
                        "processing_blocks": blocks,
                    }
                }
            }
        }
    }


# =====================================================================
# needs_migration — чистые функции
# =====================================================================


class TestNeedsMigration:
    """Тесты функции needs_migration."""

    def test_true_for_nonempty_processing_blocks(self) -> None:
        """True для данных с непустыми processing_blocks."""
        data = make_legacy_data()
        assert needs_migration(data) is True

    def test_false_for_only_nodes(self) -> None:
        """False для данных только с nodes (новый формат)."""
        data = {
            "cameras": {
                "0": {
                    "regions": {
                        "r0": {
                            "nodes": {
                                "n0": {"node_id": "n0", "operation_ref": "color_detection"}
                            }
                        }
                    }
                }
            }
        }
        assert needs_migration(data) is False

    def test_false_for_empty_data(self) -> None:
        """False для пустого dict."""
        assert needs_migration({}) is False

    def test_false_for_data_without_cameras(self) -> None:
        """False если в data нет cameras."""
        data = {"renderer": {"config": {"draw_bboxes": True}}}
        assert needs_migration(data) is False

    def test_false_for_empty_processing_blocks(self) -> None:
        """False если processing_blocks присутствует, но пустой."""
        data = {
            "cameras": {
                "0": {
                    "regions": {
                        "r0": {"processing_blocks": {}}
                    }
                }
            }
        }
        assert needs_migration(data) is False

    def test_true_if_any_region_has_blocks(self) -> None:
        """True если хотя бы одна region содержит processing_blocks."""
        data = {
            "cameras": {
                "0": {
                    "regions": {
                        "r0": {"nodes": {"n0": {}}},
                        "r1": {"processing_blocks": {"b0": {"enabled": True, "params": {}}}},
                    }
                }
            }
        }
        assert needs_migration(data) is True


# =====================================================================
# migrate_recipe_data — чистые функции
# =====================================================================


class TestMigrateRecipeData:
    """Тесты функции migrate_recipe_data."""

    def test_converts_single_block(self) -> None:
        """Конверсия одного блока: первая нода читает из frame."""
        data = make_legacy_data(
            blocks={
                "b0": {
                    "enabled": True,
                    "params": {"type": "color_detection", "color_lower": [0, 0, 0]},
                }
            }
        )
        result = migrate_recipe_data(data)

        region = result["cameras"]["0"]["regions"]["r0"]
        assert "processing_blocks" not in region
        assert "nodes" in region

        node = region["nodes"]["b0"]
        assert node["node_id"] == "b0"
        assert node["operation_ref"] == "color_detection"
        assert node["enabled"] is True
        assert node["params"] == {"color_lower": [0, 0, 0]}
        assert len(node["inputs"]) == 1
        assert node["inputs"][0]["source"] == "frame"
        assert node["inputs"][0]["output_port"] == "out"
        assert node["inputs"][0]["input_port"] == "in"

    def test_converts_three_blocks_linear_chain(self) -> None:
        """Конверсия 3 блоков: linear chain — каждая следующая ссылается на предыдущую."""
        data = {
            "cameras": {
                "0": {
                    "regions": {
                        "r0": {
                            "processing_blocks": {
                                "b0": {"enabled": True, "params": {"type": "color_detection"}},
                                "b1": {"enabled": False, "params": {"type": "blob_detection"}},
                                "b2": {"enabled": True, "params": {"type": "color_detection"}},
                            }
                        }
                    }
                }
            }
        }
        result = migrate_recipe_data(data)
        nodes = result["cameras"]["0"]["regions"]["r0"]["nodes"]

        assert nodes["b0"]["inputs"][0]["source"] == "frame"
        assert nodes["b1"]["inputs"][0]["source"] == "b0"
        assert nodes["b2"]["inputs"][0]["source"] == "b1"

        assert nodes["b1"]["enabled"] is False
        assert nodes["b0"]["operation_ref"] == "color_detection"
        assert nodes["b1"]["operation_ref"] == "blob_detection"

    def test_region_without_processing_blocks_unchanged(self) -> None:
        """Region без processing_blocks не изменяется."""
        data = {
            "cameras": {
                "0": {
                    "regions": {
                        "r0": {
                            "nodes": {"n0": {"node_id": "n0", "operation_ref": "color_detection"}},
                        }
                    }
                }
            }
        }
        result = migrate_recipe_data(data)
        region = result["cameras"]["0"]["regions"]["r0"]
        assert "nodes" in region
        assert "processing_blocks" not in region
        assert region["nodes"]["n0"]["operation_ref"] == "color_detection"

    def test_camera_without_regions_no_crash(self) -> None:
        """Camera без regions не вызывает ошибку."""
        data = {
            "cameras": {
                "0": {
                    "config": {"fps": 30},
                }
            }
        }
        result = migrate_recipe_data(data)
        assert result["cameras"]["0"]["config"]["fps"] == 30

    def test_data_without_cameras_returns_deepcopy(self) -> None:
        """data без cameras возвращается как deepcopy без изменений."""
        data = {"renderer": {"config": {"draw_bboxes": True}}}
        result = migrate_recipe_data(data)
        assert result == data
        assert result is not data

    def test_block_without_params_fallback(self, caplog) -> None:
        """Block без params → operation_ref='unknown', params={}, warning в логе."""
        data = {
            "cameras": {
                "0": {
                    "regions": {
                        "r0": {
                            "processing_blocks": {
                                "b0": {"enabled": True}  # нет params
                            }
                        }
                    }
                }
            }
        }
        with caplog.at_level(logging.WARNING):
            result = migrate_recipe_data(data)

        node = result["cameras"]["0"]["regions"]["r0"]["nodes"]["b0"]
        assert node["operation_ref"] == "unknown"
        assert node["params"] == {}
        assert any("unknown" in rec.message for rec in caplog.records)

    def test_both_blocks_and_nodes_nonempty_keeps_both(self, caplog) -> None:
        """Если непустые processing_blocks И nodes → warning, обе ветки остаются."""
        data = {
            "cameras": {
                "0": {
                    "regions": {
                        "r0": {
                            "processing_blocks": {"b0": {"enabled": True, "params": {"type": "color_detection"}}},
                            "nodes": {"n0": {"node_id": "n0", "operation_ref": "blob_detection"}},
                        }
                    }
                }
            }
        }
        with caplog.at_level(logging.WARNING):
            result = migrate_recipe_data(data)

        region = result["cameras"]["0"]["regions"]["r0"]
        # Обе ветки должны остаться
        assert "processing_blocks" in region
        assert "nodes" in region
        # warning должен быть залогирован
        assert any("processing_blocks" in rec.message and "nodes" in rec.message for rec in caplog.records)

    def test_source_dict_not_mutated(self) -> None:
        """Исходный dict не мутируется — migrate_recipe_data возвращает deepcopy."""
        data = make_legacy_data()
        original = copy.deepcopy(data)
        migrate_recipe_data(data)
        assert data == original

    def test_params_type_removed_from_node_params(self) -> None:
        """Ключ 'type' удаляется из params при конверсии."""
        data = {
            "cameras": {
                "0": {
                    "regions": {
                        "r0": {
                            "processing_blocks": {
                                "b0": {
                                    "enabled": True,
                                    "params": {
                                        "type": "color_detection",
                                        "color_lower": [10, 20, 30],
                                        "min_area": 100,
                                    },
                                }
                            }
                        }
                    }
                }
            }
        }
        result = migrate_recipe_data(data)
        node_params = result["cameras"]["0"]["regions"]["r0"]["nodes"]["b0"]["params"]
        assert "type" not in node_params
        assert node_params["color_lower"] == [10, 20, 30]
        assert node_params["min_area"] == 100

    def test_block_without_enabled_defaults_true(self) -> None:
        """Block без поля enabled → default True."""
        data = {
            "cameras": {
                "0": {
                    "regions": {
                        "r0": {
                            "processing_blocks": {
                                "b0": {"params": {"type": "color_detection"}}
                            }
                        }
                    }
                }
            }
        }
        result = migrate_recipe_data(data)
        node = result["cameras"]["0"]["regions"]["r0"]["nodes"]["b0"]
        assert node["enabled"] is True


# =====================================================================
# RecipeEngine.load() integration — миграция
# =====================================================================


class TestRecipeEngineLoadMigration:
    """Integration-тесты миграции при load()."""

    def _write_legacy_yaml(self, path: Path, name: str, blocks: dict) -> None:
        """Записывает legacy YAML-файл (v1, без meta.version)."""
        recipe = {
            "meta": {
                "name": name,
                "description": "",
                "created_at": "2024-01-01T00:00:00+00:00",
            },
            "data": {
                "cameras": {
                    "0": {
                        "regions": {
                            "r0": {
                                "processing_blocks": blocks,
                            }
                        }
                    }
                }
            },
        }
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(recipe, f, default_flow_style=False, allow_unicode=True)

    def test_bak_created_on_legacy_load(
        self, engine: RecipeEngine, recipes_dir: Path
    ) -> None:
        """.bak файл создаётся при первой загрузке legacy-рецепта."""
        yaml_path = recipes_dir / "legacy.yaml"
        self._write_legacy_yaml(
            yaml_path,
            "legacy",
            {"b0": {"enabled": True, "params": {"type": "color_detection"}}},
        )

        # Запоминаем исходный контент
        original_content = yaml_path.read_text(encoding="utf-8")

        engine.load("legacy")

        bak_path = recipes_dir / "legacy.yaml.bak"
        assert bak_path.exists(), ".bak файл должен быть создан"
        # .bak совпадает с исходным контентом
        assert bak_path.read_text(encoding="utf-8") == original_content

    def test_main_file_overwritten_with_v2(
        self, engine: RecipeEngine, recipes_dir: Path
    ) -> None:
        """Основной файл перезаписывается с meta.version=2 и nodes."""
        yaml_path = recipes_dir / "legacy.yaml"
        self._write_legacy_yaml(
            yaml_path,
            "legacy",
            {"b0": {"enabled": True, "params": {"type": "color_detection"}}},
        )

        engine.load("legacy")

        with open(yaml_path, "r", encoding="utf-8") as f:
            recipe = yaml.safe_load(f)

        assert recipe["meta"]["version"] == RECIPE_VERSION_V2
        assert recipe["meta"].get("migrated_from_v1") is True

        region = recipe["data"]["cameras"]["0"]["regions"]["r0"]
        assert "processing_blocks" not in region
        assert "nodes" in region
        assert "b0" in region["nodes"]

    def test_treestore_receives_nodes_on_legacy_load(
        self, engine: RecipeEngine, empty_store: TreeStore
    ) -> None:
        """TreeStore получает nodes при загрузке legacy-рецепта."""
        yaml_path = engine._recipes_dir / "legacy.yaml"
        self._write_legacy_yaml(
            yaml_path,
            "legacy",
            {"b0": {"enabled": True, "params": {"type": "color_detection", "color_lower": [5, 10, 15]}}},
        )

        engine.load("legacy")

        # Проверяем что store имеет operation_ref
        op_ref = empty_store.get("cameras.0.regions.r0.nodes.b0.operation_ref", default=None)
        assert op_ref == "color_detection"

    def test_repeated_load_no_re_migration(
        self, engine: RecipeEngine, recipes_dir: Path
    ) -> None:
        """Повторная загрузка мигрированного рецепта не перезаписывает .bak."""
        yaml_path = recipes_dir / "legacy.yaml"
        self._write_legacy_yaml(
            yaml_path,
            "legacy",
            {"b0": {"enabled": True, "params": {"type": "color_detection"}}},
        )

        engine.load("legacy")

        bak_path = recipes_dir / "legacy.yaml.bak"
        # Запоминаем mtime backup после первого load
        bak_mtime_1 = bak_path.stat().st_mtime

        # Второй load — не должен трогать .bak
        engine2 = RecipeEngine(store=TreeStore({}), recipes_dir=recipes_dir)
        engine2.load("legacy")

        bak_mtime_2 = bak_path.stat().st_mtime
        assert bak_mtime_1 == bak_mtime_2, ".bak не должен перезаписываться при повторной загрузке"

    def test_new_save_has_version_v2(
        self, engine: RecipeEngine, recipes_dir: Path
    ) -> None:
        """Save нового рецепта → meta.version == 2."""
        store = TreeStore({"cameras": {"0": {"config": {"fps": 30}}}})
        eng = RecipeEngine(store=store, recipes_dir=recipes_dir)
        eng.save("new_recipe")

        yaml_path = recipes_dir / "new_recipe.yaml"
        with open(yaml_path, "r", encoding="utf-8") as f:
            recipe = yaml.safe_load(f)

        assert recipe["meta"]["version"] == RECIPE_VERSION_V2


# =====================================================================
# Round-trip Pipeline через cameras
# =====================================================================


class TestPipelineRoundTrip:
    """Тесты round-trip сохранения/загрузки DAG Pipeline через cameras."""

    def test_dag_round_trip(self, recipes_dir: Path) -> None:
        """DAG-структура nodes сохраняется и восстанавливается бит-в-бит."""
        dag_data = {
            "cameras": {
                "0": {
                    "regions": {
                        "r0": {
                            "nodes": {
                                "n1": {
                                    "node_id": "n1",
                                    "operation_ref": "color_detection",
                                    "enabled": True,
                                    "params": {"color_lower": [0, 0, 0], "min_area": 100},
                                    "inputs": [
                                        {"source": "frame", "output_port": "out", "input_port": "in"}
                                    ],
                                    "outputs": [],
                                    "display_targets": [],
                                    "process_id": "processor",
                                    "worker_id": None,
                                    "position": None,
                                    "channel_prefix": None,
                                },
                                "n2": {
                                    "node_id": "n2",
                                    "operation_ref": "blob_detection",
                                    "enabled": False,
                                    "params": {"threshold_step": 5, "min_area": 50},
                                    "inputs": [
                                        {"source": "n1", "output_port": "out", "input_port": "in"}
                                    ],
                                    "outputs": [],
                                    "display_targets": [],
                                    "process_id": "processor",
                                    "worker_id": None,
                                    "position": None,
                                    "channel_prefix": None,
                                },
                            }
                        }
                    }
                }
            }
        }

        store = TreeStore(dag_data)
        engine = RecipeEngine(store=store, recipes_dir=recipes_dir)
        engine.save("dag_recipe")

        # Загружаем в чистый store
        clean_store = TreeStore({})
        engine2 = RecipeEngine(store=clean_store, recipes_dir=recipes_dir)
        engine2.load("dag_recipe")

        restored_cameras = clean_store.get("cameras")
        assert restored_cameras == dag_data["cameras"]

    def test_node_inputs_restored_correctly(self, recipes_dir: Path) -> None:
        """inputs (source, output_port, input_port) восстанавливаются корректно."""
        data = {
            "cameras": {
                "0": {
                    "regions": {
                        "r0": {
                            "nodes": {
                                "n1": {
                                    "node_id": "n1",
                                    "operation_ref": "color_detection",
                                    "enabled": True,
                                    "params": {},
                                    "inputs": [
                                        {"source": "frame", "output_port": "out", "input_port": "in"}
                                    ],
                                }
                            }
                        }
                    }
                }
            }
        }

        store = TreeStore(data)
        engine = RecipeEngine(store=store, recipes_dir=recipes_dir)
        engine.save("input_test")

        clean_store = TreeStore({})
        engine2 = RecipeEngine(store=clean_store, recipes_dir=recipes_dir)
        engine2.load("input_test")

        # Путь к inputs ноды n1
        inputs = clean_store.get(
            "cameras.0.regions.r0.nodes.n1.inputs", default=None
        )
        assert inputs is not None
        assert len(inputs) == 1
        assert inputs[0]["source"] == "frame"
        assert inputs[0]["output_port"] == "out"
        assert inputs[0]["input_port"] == "in"

    def test_migrated_legacy_dag_round_trip(
        self, recipes_dir: Path
    ) -> None:
        """Legacy-рецепт загружается через миграцию и затем сохраняется как v2."""
        legacy_recipe = {
            "meta": {"name": "legacy_dag", "description": ""},
            "data": {
                "cameras": {
                    "0": {
                        "regions": {
                            "r0": {
                                "processing_blocks": {
                                    "b0": {
                                        "enabled": True,
                                        "params": {
                                            "type": "color_detection",
                                            "color_lower": [1, 2, 3],
                                        },
                                    },
                                    "b1": {
                                        "enabled": False,
                                        "params": {"type": "blob_detection"},
                                    },
                                }
                            }
                        }
                    }
                }
            },
        }

        yaml_path = recipes_dir / "legacy_dag.yaml"
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(legacy_recipe, f, default_flow_style=False, allow_unicode=True)

        store = TreeStore({})
        engine = RecipeEngine(store=store, recipes_dir=recipes_dir)
        engine.load("legacy_dag")

        # b0 — первая нода, должна ссылаться на frame
        b0_source = store.get(
            "cameras.0.regions.r0.nodes.b0.inputs", default=None
        )
        assert b0_source is not None
        assert b0_source[0]["source"] == "frame"

        # b1 — вторая нода, должна ссылаться на b0
        b1_source = store.get(
            "cameras.0.regions.r0.nodes.b1.inputs", default=None
        )
        assert b1_source is not None
        assert b1_source[0]["source"] == "b0"

        # params сохранились без "type"
        b0_params = store.get(
            "cameras.0.regions.r0.nodes.b0.params", default=None
        )
        assert b0_params == {"color_lower": [1, 2, 3]}
