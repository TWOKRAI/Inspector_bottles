# -*- coding: utf-8 -*-
"""Task 4.2f: рецепт ``hikvision_id3013_test`` — камера MVS и считыватель ID3013 в одном рецепте.

Рецепт поднимает два независимых процесса (``camera_0`` и ``reader``), проводов между ними нет.
Тесты проверяют свойства рецепта по литералам: состав процессов, ключи камеры и считывателя,
привязку дисплея, позиции нод. ``SystemBlueprint.check() == []`` проверяет
``test_hikvision_recipes.py::test_recipe_check_is_empty[hikvision_id3013_test]``, здесь не дублируется.

Загрузка yaml — внутри фикстуры, не на уровне модуля: пока файла нет, ошибки сбора нет, а каждый
тест с фикстурой ``raw`` завершается ERROR (FileNotFoundError в фикстуре), и только
``test_engine_lists_recipe`` падает как FAILED. Красный до файла доказывает отсутствие рецепта,
а не чувствительность каждого утверждения.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

_RECIPES_DIR = Path(__file__).resolve().parents[1]
_RECIPE = "hikvision_id3013_test"


@pytest.fixture
def raw() -> dict[str, Any]:
    return yaml.safe_load((_RECIPES_DIR / f"{_RECIPE}.yaml").read_text(encoding="utf-8"))


def _process(raw: dict[str, Any], name: str) -> dict[str, Any]:
    return next(p for p in raw["blueprint"]["processes"] if p["process_name"] == name)


def _plugin(raw: dict[str, Any], process_name: str) -> dict[str, Any]:
    return _process(raw, process_name)["plugins"][0]


def test_engine_lists_recipe() -> None:
    from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore
    from multiprocess_prototype.backend.state.recipes.recipe_engine import RecipeEngine

    engine = RecipeEngine(store=TreeStore(), recipes_dir=_RECIPES_DIR)
    assert "hikvision_id3013_test" in engine.list()


def test_name_blueprint_name_and_version(raw: dict[str, Any]) -> None:
    assert raw["name"] == "hikvision_id3013_test"
    assert raw["blueprint"]["name"] == "hikvision_id3013_test"
    assert raw["version"] == 3


def test_process_names_and_order(raw: dict[str, Any]) -> None:
    assert [p["process_name"] for p in raw["blueprint"]["processes"]] == ["gui", "camera_0", "reader"]


def test_camera_0_block(raw: dict[str, Any]) -> None:
    proc = _process(raw, "camera_0")
    plugin = _plugin(raw, "camera_0")
    assert plugin["device_select"] == "serial"
    assert plugin["device_serial"] == "DA1689923"
    assert plugin["camera_id"] == 0
    assert plugin["trigger_mode"] == "Off"  # строка, не bool False
    assert isinstance(plugin["trigger_mode"], str)
    assert proc["chain_targets"] == ["gui"]


def test_reader_block(raw: dict[str, Any]) -> None:
    proc = _process(raw, "reader")
    plugin = _plugin(raw, "reader")
    assert plugin["plugin_name"] == "code_reader"
    assert plugin["host"] == "0.0.0.0"
    assert plugin["port"] == 5000
    assert plugin["terminator"] == "\n"
    assert proc["chain_targets"] == ["gui"]


def test_reader_text_settings_and_autostart(raw: dict[str, Any]) -> None:
    plugin = _plugin(raw, "reader")
    assert plugin["reader_id"] == "id3013"
    assert plugin["no_code_text"] == "NoRead"
    assert plugin["bad_code_text"] == ""
    assert plugin["prefix"] == ""
    assert plugin["auto_start"] is True


def test_exactly_one_plugin_listens_on_port_5000(raw: dict[str, Any]) -> None:
    plugins = [pl for proc in raw["blueprint"]["processes"] for pl in proc.get("plugins") or []]
    assert sum(1 for pl in plugins if pl.get("port") == 5000) == 1


def test_no_wires_and_single_display_binding(raw: dict[str, Any]) -> None:
    assert raw["blueprint"]["wires"] == []
    assert raw["blueprint"]["displays"] == [{"node_id": "camera_0.hikvision.frame", "display_id": "main"}]


def test_top_level_displays_define_bound_display(raw: dict[str, Any]) -> None:
    assert [d["id"] for d in raw["displays"]] == ["main"]
    assert raw["blueprint"]["displays"][0]["display_id"] in ["main"]


def test_gui_positions_and_locked_nodes(raw: dict[str, Any]) -> None:
    metadata = raw["blueprint"]["metadata"]
    assert sorted(metadata["gui_positions"]) == ["camera_0.hikvision", "main", "reader.code_reader"]
    assert metadata["locked_nodes"] == []
