# -*- coding: utf-8 -*-
"""Task 4.2g: рецепт ``hikvision_id3013_view`` — камера MVS и два считывателя ID3013 (SDK), три дисплея.

Рецепт поднимает камеру ``camera_0`` и две независимые цепочки ``reader_N -> draw_N``; кадры идут
на три дисплея: ``camera``, ``reader_1``, ``reader_2``. Тесты проверяют свойства рецепта по литералам:
состав и порядок процессов, ключи камеры и считывателей, провода, привязки дисплеев, геометрию дисплеев,
позиции нод. ``SystemBlueprint.check() == []`` проверяет
``test_hikvision_recipes.py::test_recipe_check_is_empty[hikvision_id3013_view]``, здесь не дублируется.

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
_RECIPE = "hikvision_id3013_view"

# Группы стиля, которые обязан знать overlay_draw (литерал, не читается из образца dual).
_COLOR_GROUPS = ["code_ok", "code_bad", "status_ok", "status_bad", "code_text_ok", "code_text_bad"]


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
    assert "hikvision_id3013_view" in engine.list()


def test_name_blueprint_name_and_version(raw: dict[str, Any]) -> None:
    assert raw["name"] == "hikvision_id3013_view"
    assert raw["blueprint"]["name"] == "hikvision_id3013_view"
    assert raw["version"] == 3


def test_process_names_and_order(raw: dict[str, Any]) -> None:
    assert [p["process_name"] for p in raw["blueprint"]["processes"]] == [
        "gui",
        "camera_0",
        "reader_1",
        "draw_1",
        "reader_2",
        "draw_2",
    ]


@pytest.mark.parametrize(
    ("process", "process_class", "plugin_class"),
    [
        ("gui", "multiprocess_prototype.frontend.headless_process.HeadlessGuiProcess", None),
        (
            "camera_0",
            "multiprocess_prototype.generic_process_app.GenericProcessApp",
            "Services.hikvision_camera.plugin.plugin.HikvisionCameraPlugin",
        ),
        (
            "reader_1",
            "multiprocess_prototype.generic_process_app.GenericProcessApp",
            "Services.code_reader.plugin.sdk_plugin.CodeReaderSdkPlugin",
        ),
        (
            "draw_1",
            "multiprocess_prototype.generic_process_app.GenericProcessApp",
            "Plugins.render.overlay_draw.plugin.OverlayDrawPlugin",
        ),
        (
            "reader_2",
            "multiprocess_prototype.generic_process_app.GenericProcessApp",
            "Services.code_reader.plugin.sdk_plugin.CodeReaderSdkPlugin",
        ),
        (
            "draw_2",
            "multiprocess_prototype.generic_process_app.GenericProcessApp",
            "Plugins.render.overlay_draw.plugin.OverlayDrawPlugin",
        ),
    ],
)
def test_process_and_plugin_classes(
    raw: dict[str, Any], process: str, process_class: str, plugin_class: str | None
) -> None:
    proc = _process(raw, process)
    assert proc["process_class"] == process_class
    if plugin_class is None:
        assert not proc["plugins"]
    else:
        assert len(proc["plugins"]) == 1
        assert proc["plugins"][0]["plugin_class"] == plugin_class


def test_camera_0_block(raw: dict[str, Any]) -> None:
    proc = _process(raw, "camera_0")
    plugin = _plugin(raw, "camera_0")
    assert plugin["device_select"] == "serial"
    assert plugin["device_serial"] == "DA1689923"
    assert plugin["camera_id"] == 0
    assert plugin["trigger_mode"] == "Off"  # строка, не bool False
    assert isinstance(plugin["trigger_mode"], str)
    assert proc["chain_targets"] == ["gui"]
    assert proc["source_target_fps"] == 25


@pytest.mark.parametrize(
    ("reader", "draw", "device_ip", "reader_id"),
    [
        ("reader_1", "draw_1", "192.168.1.10", "id3013-sdk-1"),
        ("reader_2", "draw_2", "192.168.1.11", "id3013-sdk-2"),
    ],
)
def test_reader_block(raw: dict[str, Any], reader: str, draw: str, device_ip: str, reader_id: str) -> None:
    proc = _process(raw, reader)
    plugin = _plugin(raw, reader)
    assert plugin["plugin_name"] == "code_reader_sdk"
    assert plugin["device_ip"] == device_ip
    assert plugin["reader_id"] == reader_id
    assert plugin["auto_start"] is True
    assert plugin["timeout_ms"] == 500
    assert proc["chain_targets"] == [draw]
    assert proc["source_target_fps"] == 20
    assert [label["per"] for label in plugin["labels"]] == ["frame", "code"]
    assert [label["group"] for label in plugin["labels"]] == ["status_{state}", "code_text_{state}"]


def test_readers_have_distinct_nonempty_device_ips(raw: dict[str, Any]) -> None:
    ip_1 = _plugin(raw, "reader_1")["device_ip"]
    ip_2 = _plugin(raw, "reader_2")["device_ip"]
    assert ip_1
    assert ip_2
    assert ip_1 != ip_2


@pytest.mark.parametrize("draw", ["draw_1", "draw_2"])
def test_draw_block(raw: dict[str, Any], draw: str) -> None:
    proc = _process(raw, draw)
    plugin = _plugin(raw, draw)
    assert plugin["plugin_name"] == "overlay_draw"
    assert proc["chain_targets"] == ["gui"]
    groups = [row["group"] for row in plugin["color_table"]]
    for group in _COLOR_GROUPS:
        assert group in groups


def test_wires_are_exactly_two_reader_to_draw(raw: dict[str, Any]) -> None:
    assert raw["blueprint"]["wires"] == [
        {"source": "reader_1.code_reader_sdk.frame", "target": "draw_1.overlay_draw.frame"},
        {"source": "reader_2.code_reader_sdk.frame", "target": "draw_2.overlay_draw.frame"},
    ]


def test_display_bindings_are_exactly_three(raw: dict[str, Any]) -> None:
    assert raw["blueprint"]["displays"] == [
        {"node_id": "camera_0.hikvision.frame", "display_id": "camera"},
        {"node_id": "draw_1.overlay_draw.frame", "display_id": "reader_1"},
        {"node_id": "draw_2.overlay_draw.frame", "display_id": "reader_2"},
    ]


def test_top_level_displays_define_bound_displays(raw: dict[str, Any]) -> None:
    ids = ["camera", "reader_1", "reader_2"]
    assert [d["id"] for d in raw["displays"]] == ids
    for binding in raw["blueprint"]["displays"]:
        assert binding["display_id"] in ids


def test_display_format_geometry_and_positions(raw: dict[str, Any]) -> None:
    displays = raw["displays"]
    assert [d["format"] for d in displays] == ["BGR", "BGR", "BGR"]
    assert [(d["width"], d["height"], d["fps_limit"], d["position"]["x"], d["position"]["y"]) for d in displays] == [
        (1280, 720, 30.0, 0, 0),
        (1280, 1024, 20.0, 1290, 0),
        (1280, 1024, 20.0, 2580, 0),
    ]


def test_no_plugin_has_port_key(raw: dict[str, Any]) -> None:
    plugins = [pl for proc in raw["blueprint"]["processes"] for pl in proc.get("plugins") or []]
    assert len(plugins) == 5
    assert [pl for pl in plugins if "port" in pl] == []


def test_gui_positions_and_locked_nodes(raw: dict[str, Any]) -> None:
    metadata = raw["blueprint"]["metadata"]
    assert sorted(metadata["gui_positions"]) == [
        "camera_0.hikvision",
        "draw_1.overlay_draw",
        "draw_2.overlay_draw",
        "reader_1.code_reader_sdk",
        "reader_2.code_reader_sdk",
    ]
    assert metadata["locked_nodes"] == []
