# -*- coding: utf-8 -*-
"""Task T7: рецепт ``gui_overload_synth`` — четыре больших синтетических потока в окно, без железа.

Рецепт для стенда перегрузки gui до и после T3: четыре ``SyntheticFrameSourcePlugin`` (2 x 1440x1080
и 2 x 1280x1024, по 50 кадр/с, суммарно 200 кадр/с) идут напрямую в gui, четыре дисплея с
``fps_limit`` 30 / 30 / 20 / 20. Тесты проверяют свойства рецепта по литералам: порядок процессов,
размер и частоту каждого источника, геометрию и пределы дисплеев, привязки, карту маршрутизации
кадров боевой ``build_frame_routing`` и отсутствие железа (белый список плагинов).

Загрузка yaml — внутри фикстуры, не на уровне модуля: пока файла нет, ошибки сбора нет, а каждый
тест с фикстурой ``raw`` или ``recipe_path`` завершается ERROR (AssertionError «нет файла рецепта» из
``recipe_path``), и только ``test_engine_lists_recipe`` падает как FAILED.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

_RECIPES_DIR = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _RECIPES_DIR.parents[1]
_RECIPE = "gui_overload_synth"
_SYNTH_CLASS = "Plugins.sources.synthetic_frame_source.plugin.SyntheticFrameSourcePlugin"


@pytest.fixture
def recipe_path() -> Path:
    path = _RECIPES_DIR / f"{_RECIPE}.yaml"
    assert path.is_file(), f"нет файла рецепта: {path}"
    return path


@pytest.fixture
def raw(recipe_path: Path) -> dict[str, Any]:
    return yaml.safe_load(recipe_path.read_text(encoding="utf-8"))


@pytest.fixture
def plugins_discovered() -> None:
    from multiprocess_framework.modules.app_module import discover
    from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry

    discover(plugin_paths=[str(_PROJECT_ROOT / "Plugins"), str(_PROJECT_ROOT / "Services")], service_paths=[])
    assert PluginRegistry.get("synthetic_frame_source") is not None, "реестр пуст: check() ничего бы не проверил"


def _process(raw: dict[str, Any], name: str) -> dict[str, Any]:
    return next(p for p in raw["blueprint"]["processes"] if p["process_name"] == name)


def _plugin(raw: dict[str, Any], process_name: str) -> dict[str, Any]:
    return _process(raw, process_name)["plugins"][0]


def test_engine_lists_recipe() -> None:
    from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore
    from multiprocess_prototype.backend.state.recipes.recipe_engine import RecipeEngine

    engine = RecipeEngine(store=TreeStore(), recipes_dir=_RECIPES_DIR)
    assert "gui_overload_synth" in engine.list()


def test_recipe_validates(recipe_path: Path, plugins_discovered: None) -> None:
    """Рецепт читается боевым путём загрузки и проходит ``SystemBlueprint.check()`` без ошибок."""
    from multiprocess_framework.modules.process_manager_module.topology.blueprint import SystemBlueprint
    from multiprocess_prototype.backend.assembly.normalize import normalize_blueprint
    from multiprocess_prototype.backend.config.schemas import load_system_config
    from multiprocess_prototype.backend.launch import load_topology_dict

    topology = SystemBlueprint.model_validate(
        normalize_blueprint(load_topology_dict(recipe_path), load_system_config())
    )
    topology.infer_missing_collectors()
    errors = topology.check()
    assert errors == [], "check() вернул ошибки:\n  " + "\n  ".join(errors)


def test_name_blueprint_name_and_version(raw: dict[str, Any]) -> None:
    assert raw["name"] == "gui_overload_synth"
    assert raw["blueprint"]["name"] == "gui_overload_synth"
    assert raw["version"] == 1


def test_process_names_and_order(raw: dict[str, Any]) -> None:
    assert [p["process_name"] for p in raw["blueprint"]["processes"]] == [
        "gui",
        "camera_0",
        "camera_1",
        "camera_2",
        "camera_3",
    ]


def test_gui_process_is_headless_class(raw: dict[str, Any]) -> None:
    gui = _process(raw, "gui")
    assert gui["process_class"] == "multiprocess_prototype.frontend.headless_process.HeadlessGuiProcess"
    assert gui["chain_targets"] == []
    assert gui["protected"] is True
    assert not gui["plugins"]


@pytest.mark.parametrize(
    ("camera", "camera_id", "width", "height"),
    [
        ("camera_0", 0, 1440, 1080),
        ("camera_1", 1, 1440, 1080),
        ("camera_2", 2, 1280, 1024),
        ("camera_3", 3, 1280, 1024),
    ],
)
def test_source_size_and_fps_per_camera(
    raw: dict[str, Any], camera: str, camera_id: int, width: int, height: int
) -> None:
    proc = _process(raw, camera)
    plugin = _plugin(raw, camera)
    assert proc["process_class"] == "multiprocess_prototype.generic_process_app.GenericProcessApp"
    assert proc["chain_targets"] == ["gui"]
    assert proc["source_target_fps"] == 50  # на уровне процесса
    assert "source_target_fps" not in plugin  # внутри плагина ключ молча игнорировался бы
    assert plugin["plugin_class"] == _SYNTH_CLASS
    assert plugin["plugin_name"] == "synthetic_frame_source"
    assert plugin["category"] == "source"
    assert plugin["camera_id"] == camera_id
    assert plugin["resolution_width"] == width
    assert plugin["resolution_height"] == height


def test_cameras_have_distinct_ids(raw: dict[str, Any]) -> None:
    ids = [_plugin(raw, f"camera_{n}")["camera_id"] for n in range(4)]
    assert sorted(ids) == [0, 1, 2, 3]


def test_four_sources_routed_to_four_displays(raw: dict[str, Any]) -> None:
    assert raw["blueprint"]["displays"] == [
        {"node_id": "camera_0.synthetic_frame_source.frame", "display_id": "camera_0"},
        {"node_id": "camera_1.synthetic_frame_source.frame", "display_id": "camera_1"},
        {"node_id": "camera_2.synthetic_frame_source.frame", "display_id": "camera_2"},
        {"node_id": "camera_3.synthetic_frame_source.frame", "display_id": "camera_3"},
    ]
    assert [d["id"] for d in raw["displays"]] == ["camera_0", "camera_1", "camera_2", "camera_3"]


def test_frame_routing_via_build_frame_routing(raw: dict[str, Any]) -> None:
    from multiprocess_prototype.frontend.widgets.image_panel.recipe_displays import build_frame_routing

    assert build_frame_routing(raw) == {
        "camera_0": "camera_0",
        "camera_1": "camera_1",
        "camera_2": "camera_2",
        "camera_3": "camera_3",
    }


def test_display_fps_limit_and_size(raw: dict[str, Any]) -> None:
    displays = raw["displays"]
    assert [(d["width"], d["height"], d["fps_limit"], d["position"]["x"], d["position"]["y"]) for d in displays] == [
        (1440, 1080, 30.0, 0, 0),
        (1440, 1080, 30.0, 1290, 0),
        (1280, 1024, 20.0, 2580, 0),
        (1280, 1024, 20.0, 3870, 0),
    ]
    assert all(isinstance(d["fps_limit"], float) for d in displays)
    assert [d["format"] for d in displays] == ["BGR", "BGR", "BGR", "BGR"]


def test_display_names_fit_and_ring_buffer(raw: dict[str, Any]) -> None:
    displays = raw["displays"]
    assert [d["name"] for d in displays] == [
        "Синтетика 0 (1440x1080, 50 Гц)",
        "Синтетика 1 (1440x1080, 50 Гц)",
        "Синтетика 2 (1280x1024, 50 Гц)",
        "Синтетика 3 (1280x1024, 50 Гц)",
    ]
    assert [d["fit"] for d in displays] == ["contain", "contain", "contain", "contain"]
    assert [d["ring_buffer_blocks"] for d in displays] == [3, 3, 3, 3]
    assert [d["scale"] for d in displays] == [100, 100, 100, 100]
    assert [d["rotate"] for d in displays] == [0, 0, 0, 0]
    assert [d["flip"] for d in displays] == ["none", "none", "none", "none"]


def test_no_hardware_plugins(raw: dict[str, Any]) -> None:
    """Белый список: только синтетические источники, секции устройств (робот, VFD) нет."""
    plugins = [pl for proc in raw["blueprint"]["processes"] for pl in proc.get("plugins") or []]
    assert len(plugins) == 4
    assert {pl["plugin_class"] for pl in plugins} == {_SYNTH_CLASS}
    assert [pl["plugin_name"] for pl in plugins] == ["synthetic_frame_source"] * 4
    assert "devices" not in raw
