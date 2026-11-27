# -*- coding: utf-8 -*-
"""Task 4.2i: рецепт ``hikvision_id3013_quad`` — две камеры MVS и два считывателя ID3013 (SDK), четыре дисплея.

Рецепт поднимает ``camera_0`` и ``camera_1`` (каждая в своём процессе) и две независимые цепочки
``reader_N -> draw_N``; кадры идут на четыре дисплея: ``camera_0``, ``camera_1``, ``reader_1``, ``reader_2``.
Тесты проверяют свойства рецепта по литералам: состав и порядок процессов, ключи камер и считывателей,
режим самотриггера ``reader_2``, провода, привязки и геометрию дисплеев, позиции нод.
``SystemBlueprint.check() == []`` проверяет ``test_hikvision_recipes.py::test_recipe_check_is_empty``,
здесь не дублируется.

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

from multiprocess_prototype.frontend.widgets.image_panel.recipe_displays import build_plate_sources

_RECIPES_DIR = Path(__file__).resolve().parents[1]
_RECIPE = "hikvision_id3013_quad"

# Группы стиля, которые обязан знать overlay_draw (литерал, не читается из образца dual).
_COLOR_GROUPS = ["code_ok", "code_bad", "status_ok", "status_bad", "code_text_ok", "code_text_bad"]
_TRIGGER_KEYS = ("trigger_mode", "trigger_source", "trigger_period_ms")


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
    assert "hikvision_id3013_quad" in engine.list()


def test_name_blueprint_name_and_version(raw: dict[str, Any]) -> None:
    assert raw["name"] == "hikvision_id3013_quad"
    assert raw["blueprint"]["name"] == "hikvision_id3013_quad"
    assert raw["version"] == 3


def test_process_names_and_order(raw: dict[str, Any]) -> None:
    assert [p["process_name"] for p in raw["blueprint"]["processes"]] == [
        "gui",
        "camera_0",
        "camera_1",
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
            "camera_1",
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


@pytest.mark.parametrize(
    ("camera", "camera_id", "serial"),
    [("camera_0", 0, "DA1689923"), ("camera_1", 1, "DA1689977")],
)
def test_camera_block(raw: dict[str, Any], camera: str, camera_id: int, serial: str) -> None:
    proc = _process(raw, camera)
    plugin = _plugin(raw, camera)
    assert plugin["plugin_name"] == "hikvision"
    assert plugin["device_select"] == "serial"
    assert plugin["device_serial"] == serial
    assert plugin["camera_id"] == camera_id
    assert plugin["trigger_mode"] == "Off"  # строка, не bool False
    assert isinstance(plugin["trigger_mode"], str)
    assert "gain_auto" not in plugin  # при Continuous усиление молча не пишется
    assert proc["chain_targets"] == ["gui"]
    assert proc["source_target_fps"] == 25
    assert proc["priority"] == "high"


def test_camera_1_gain_is_float_and_camera_0_has_none(raw: dict[str, Any]) -> None:
    gain = _plugin(raw, "camera_1")["gain"]
    assert gain == 23.0
    assert isinstance(gain, float)
    assert "gain" not in _plugin(raw, "camera_0")


def test_cameras_have_distinct_serials_and_ids(raw: dict[str, Any]) -> None:
    cam_0 = _plugin(raw, "camera_0")
    cam_1 = _plugin(raw, "camera_1")
    assert cam_0["device_serial"] != cam_1["device_serial"]
    assert cam_0["camera_id"] != cam_1["camera_id"]


@pytest.mark.parametrize("camera", ["camera_0", "camera_1"])
def test_camera_config_builds_into_register_without_validation_error(raw: dict[str, Any], camera: str) -> None:
    from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
    from Services.hikvision_camera.plugin.registers import HikvisionCameraRegisters

    cfg = PluginOrchestrator._extract_plugin_config(_plugin(raw, camera))
    register = HikvisionCameraRegisters()
    fields = set(HikvisionCameraRegisters.model_fields)
    for key, value in cfg.items():
        if key in fields:
            setattr(register, key, value)  # validate_assignment: ValidationError при значении вне диапазона
    assert register.device_serial == cfg["device_serial"]


@pytest.mark.parametrize(
    ("reader", "draw", "device_ip", "reader_id", "prefix"),
    [
        ("reader_1", "draw_1", "192.168.1.10", "id3013-sdk-1", "cam1"),
        ("reader_2", "draw_2", "192.168.1.11", "id3013-sdk-2", "cam2"),
    ],
)
def test_reader_block(raw: dict[str, Any], reader: str, draw: str, device_ip: str, reader_id: str, prefix: str) -> None:
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
    assert plugin["labels"][0]["template"] == prefix + " {status} | ok {ok} / no {no} / bad {bad}"
    assert plugin["labels"][1]["template"] == "{code}"


def test_reader_1_writes_no_trigger_mode(raw: dict[str, Any]) -> None:
    plugin = _plugin(raw, "reader_1")
    assert [key for key in _TRIGGER_KEYS if key in plugin] == []


def test_reader_2_self_trigger_mode(raw: dict[str, Any]) -> None:
    plugin = _plugin(raw, "reader_2")
    assert plugin["trigger_mode"] == "On"  # строка, не bool True
    assert isinstance(plugin["trigger_mode"], str)
    assert plugin["trigger_source"] == "SelfTrigger"
    assert plugin["trigger_period_ms"] == 40


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


def test_display_bindings_are_exactly_four(raw: dict[str, Any]) -> None:
    assert raw["blueprint"]["displays"] == [
        {"node_id": "camera_0.hikvision.frame", "display_id": "camera_0"},
        {"node_id": "camera_1.hikvision.frame", "display_id": "camera_1"},
        {"node_id": "draw_1.overlay_draw.frame", "display_id": "reader_1"},
        {"node_id": "draw_2.overlay_draw.frame", "display_id": "reader_2"},
    ]


def test_top_level_displays_define_bound_displays(raw: dict[str, Any]) -> None:
    ids = ["camera_0", "camera_1", "reader_1", "reader_2"]
    assert [d["id"] for d in raw["displays"]] == ids
    for binding in raw["blueprint"]["displays"]:
        assert binding["display_id"] in ids


def test_display_format_geometry_and_positions(raw: dict[str, Any]) -> None:
    displays = raw["displays"]
    assert [d["format"] for d in displays] == ["BGR", "BGR", "BGR", "BGR"]
    assert [(d["width"], d["height"], d["fps_limit"], d["position"]["x"], d["position"]["y"]) for d in displays] == [
        (1280, 720, 30.0, 0, 0),
        (1280, 720, 30.0, 1290, 0),
        (1280, 1024, 20.0, 2580, 0),
        (1280, 1024, 20.0, 3870, 0),
    ]


def test_display_names_fit_and_ring_buffer(raw: dict[str, Any]) -> None:
    displays = raw["displays"]
    assert [d["name"] for d in displays] == [
        "Камера MVS 0 (DA1689923)",
        "Камера MVS 1 (DA1689977)",
        "Считыватель 1 (.10)",
        "Считыватель 2 (.11, самотриггер)",
    ]
    assert [d["fit"] for d in displays] == ["contain", "contain", "contain", "contain"]
    assert [d["ring_buffer_blocks"] for d in displays] == [3, 3, 3, 3]


def test_no_plugin_has_port_key(raw: dict[str, Any]) -> None:
    plugins = [pl for proc in raw["blueprint"]["processes"] for pl in proc.get("plugins") or []]
    assert len(plugins) == 6
    assert [pl for pl in plugins if "port" in pl] == []


def test_gui_positions_and_locked_nodes(raw: dict[str, Any]) -> None:
    metadata = raw["blueprint"]["metadata"]
    assert metadata["gui_positions"] == {
        "camera_0.hikvision": [40.0, 40.0],
        "camera_1.hikvision": [40.0, 120.0],
        "reader_1.code_reader_sdk": [40.0, 200.0],
        "draw_1.overlay_draw": [360.0, 200.0],
        "reader_2.code_reader_sdk": [40.0, 360.0],
        "draw_2.overlay_draw": [360.0, 360.0],
    }
    assert metadata["locked_nodes"] == []


def test_displays_show_plate_on_silence(raw: dict[str, Any]) -> None:
    """Свободный ход: все четыре экрана — плашка по тишине (порог по умолчанию), и это проходит ``Recipe``."""
    from multiprocess_prototype.domain.entities.recipe import Recipe

    assert [d.get("plate_mode") for d in raw["displays"]] == ["silence", "silence", "silence", "silence"]
    assert [d for d in raw["displays"] if "plate_after_s" in d] == []

    displays = Recipe.from_dict(raw).displays
    assert [(d.id, d.plate_mode, d.plate_after_s) for d in displays] == [
        ("camera_0", "silence", 2),
        ("camera_1", "silence", 2),
        ("reader_1", "silence", 2),
        ("reader_2", "silence", 2),
    ]


def test_hardware_trigger_recipe_has_no_plate_mode() -> None:
    """``quad_hw``: между триггерами кадров нет, ``silence`` мигал бы плашкой."""
    hw = yaml.safe_load((_RECIPES_DIR / "hikvision_id3013_quad_hw.yaml").read_text(encoding="utf-8"))

    assert len(hw["displays"]) == 4
    assert [d for d in hw["displays"] if "plate_mode" in d] == []


def test_reader_plates_name_the_reader_not_the_drawer(raw: dict[str, Any]) -> None:
    """Плашка экрана считывателя берёт номер и адрес прибора, а не отрисовщика draw_N."""
    sources = build_plate_sources(raw)

    assert [
        (d, sources[d]["source"], sources[d]["process"], sources[d]["number"], sources[d]["address"])
        for d in ("reader_1", "reader_2")
    ] == [
        ("reader_1", "reader_1.code_reader_sdk", "reader_1", "id3013-sdk-1", "192.168.1.10"),
        ("reader_2", "reader_2.code_reader_sdk", "reader_2", "id3013-sdk-2", "192.168.1.11"),
    ]
