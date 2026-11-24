# -*- coding: utf-8 -*-
"""Task 4.3 (T10b, К4): рецепты ``hikvision`` задают камеру полями нового register'а.

Старые ключи ``camera_index`` / ``fps`` плагин молча игнорирует (в register'е нет таких полей),
поэтому тест проверяет и отсутствие старых ключей, и наличие новых, и загрузку рецепта той же
проверкой, что зовёт запуск (``SystemBlueprint.check``). Ожидаемые значения — литералы.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from multiprocess_framework.modules.process_manager_module.topology.blueprint import SystemBlueprint
from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry
from Services.hikvision_camera.plugin.registers import HikvisionCameraRegisters

_RECIPES_DIR = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _RECIPES_DIR.parents[1]

_SINGLE = ("hikvision_inspect", "hikvision_letter_robot", "camera_robot_calibration", "dataset_circle_capture")
_ALL = (*_SINGLE, "hikvision_dual", "hikvision_id3013_test", "hikvision_id3013_view")

_PLUGIN_CLASS = "Services.hikvision_camera.plugin.plugin.HikvisionCameraPlugin"
_SERIAL_0 = "DA1689923"  # факт 0.5: MV-CS020-10GC на стенде
_PROCESS_LEVEL_KEYS = {"restart_policy", "source_target_fps"}


def _raw(name: str) -> dict[str, Any]:
    return yaml.safe_load((_RECIPES_DIR / f"{name}.yaml").read_text(encoding="utf-8"))


def _camera_nodes(name: str) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    """process_name -> (узел процесса, конфиг плагина камеры как его читает плагин в бою)."""
    result: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for proc in _raw(name)["blueprint"]["processes"]:
        for pdef in proc.get("plugins") or []:
            if pdef.get("plugin_class") == _PLUGIN_CLASS:
                result[proc["process_name"]] = (proc, PluginOrchestrator._extract_plugin_config(pdef))
    return result


@pytest.mark.parametrize("name", _ALL)
def test_recipe_has_hikvision_camera(name: str) -> None:
    assert _camera_nodes(name), f"{name}: нет плагина HikvisionCameraPlugin"


@pytest.mark.parametrize("name", _ALL)
def test_camera_keys_are_register_fields(name: str) -> None:
    fields = set(HikvisionCameraRegisters.model_fields)
    # ключи самого плагина (имя, класс, категория), run_locked_commands и readiness читает плагин, не register
    allowed = fields | {"plugin_name", "plugin_class", "category", "run_locked_commands", "readiness"}
    for proc, cfg in _camera_nodes(name).values():
        unknown = set(cfg) - allowed
        assert not unknown, f"{name}: ключи вне register'а: {sorted(unknown)}"
        assert not (set(cfg) & _PROCESS_LEVEL_KEYS), f"{name}: ключи процесса попали в плагин"


@pytest.mark.parametrize("name", _ALL)
def test_old_keys_are_gone(name: str) -> None:
    for cfg in (c for _, c in _camera_nodes(name).values()):
        assert "camera_index" not in cfg
        assert "fps" not in cfg


@pytest.mark.parametrize("name", _ALL)
def test_camera_fields_set_explicitly(name: str) -> None:
    for _, cfg in _camera_nodes(name).values():
        assert cfg["frame_rate"] == 25.0
        assert cfg["frame_rate_enable"] is True
        assert cfg["exposure_time"] == 40000.0
        assert cfg["auto_start"] is True
        assert cfg["resolution_width"] == 1440
        assert cfg["resolution_height"] == 1080
        assert cfg["run_locked_commands"] == ["release_device", "take_device"]
        # packet_size: числа с дня №1 нет, 0 использовать нельзя
        assert cfg.get("packet_size", 1500) != 0


@pytest.mark.parametrize("name", _SINGLE)
def test_single_camera_recipe_selects_serial(name: str) -> None:
    nodes = _camera_nodes(name)
    assert list(nodes) == ["camera_0"]
    cfg = nodes["camera_0"][1]
    assert cfg["camera_id"] == 0
    assert cfg["device_select"] == "serial"
    assert cfg["device_serial"] == _SERIAL_0


@pytest.mark.parametrize("name", _ALL)
def test_camera_block_manages_trigger_off(name: str) -> None:
    # старый HikvisionCamera.open писал TriggerMode=Off при каждом open; новый путь по умолчанию не пишет
    for _, cfg in _camera_nodes(name).values():
        assert cfg["trigger_managed"] is True
        assert cfg["trigger_mode"] == "Off"


def _processes_after_camera(name: str, camera: str, depth: int = 2) -> list[dict[str, Any]]:
    """Процессы, принимающие кадр камеры: по chain_targets и по проводам, не дальше ``depth`` шагов."""
    bp = _raw(name)["blueprint"]
    by_name = {p["process_name"]: p for p in bp["processes"]}
    edges: dict[str, set[str]] = {}
    for proc in bp["processes"]:
        edges.setdefault(proc["process_name"], set()).update(proc.get("chain_targets") or [])
    for wire in bp.get("wires") or []:
        edges.setdefault(wire["source"].split(".")[0], set()).add(wire["target"].split(".")[0])
    found: list[str] = []
    frontier = [camera]
    for _ in range(depth):
        frontier = [t for p in frontier for t in sorted(edges.get(p, ())) if t in by_name and t not in found]
        found.extend(frontier)
    return [by_name[n] for n in found]


@pytest.mark.parametrize("name", _ALL)
def test_no_color_convert_among_first_plugins_after_camera(name: str) -> None:
    # камера на ядре отдаёт BGR: color_convert bgr2rgb после неё инвертировал бы цвет
    for camera in _camera_nodes(name):
        after = _processes_after_camera(name, camera)
        assert after, f"{name}: после {camera} нет процессов — проверка ничего бы не увидела"
        for proc in after:
            first_three = [p["plugin_name"] for p in (proc.get("plugins") or [])[:3]]
            assert "color_convert" not in first_three, f"{name}: {proc['process_name']} -> {first_three}"


def test_dual_recipe_two_cameras_two_serials_backoff_10() -> None:
    nodes = _camera_nodes("hikvision_dual")
    assert sorted(nodes) == ["camera_0", "camera_1"]
    cfg0, cfg1 = nodes["camera_0"][1], nodes["camera_1"][1]
    assert (cfg0["camera_id"], cfg1["camera_id"]) == (0, 1)
    assert cfg0["device_select"] == "serial"
    assert cfg0["device_serial"] == _SERIAL_0
    assert cfg1["device_select"] == "serial"
    assert cfg1["device_serial"] and cfg1["device_serial"] != _SERIAL_0
    for proc, _ in nodes.values():
        assert proc["restart_policy"]["backoff_sec"] == 10.0


def test_hikvision_inspect_wires_camera_straight_to_display() -> None:
    raw = _raw("hikvision_inspect")
    bp = raw["blueprint"]
    text = (_RECIPES_DIR / "hikvision_inspect.yaml").read_text(encoding="utf-8")
    assert [p["process_name"] for p in bp["processes"]] == ["gui", "camera_0"]
    assert bp["displays"] == [{"node_id": "camera_0.hikvision.frame", "display_id": "main"}]
    assert sorted(bp["metadata"]["gui_positions"]) == ["camera_0.hikvision", "main"]
    assert "ColorConvertPlugin" not in text


# --------------------------------------------------------------------------- загрузчик


@pytest.fixture
def plugins_discovered() -> None:
    from multiprocess_framework.modules.app_module import discover

    discover(plugin_paths=[str(_PROJECT_ROOT / "Plugins"), str(_PROJECT_ROOT / "Services")], service_paths=[])
    assert PluginRegistry.get("hikvision") is not None, "реестр пуст: check() ничего бы не проверил"


@pytest.mark.parametrize("name", _ALL)
def test_recipe_check_is_empty(name: str, plugins_discovered: None) -> None:
    from multiprocess_prototype.backend.assembly.normalize import normalize_blueprint
    from multiprocess_prototype.backend.config.schemas import load_system_config
    from multiprocess_prototype.backend.launch import load_topology_dict

    topology = SystemBlueprint.model_validate(
        normalize_blueprint(load_topology_dict(_RECIPES_DIR / f"{name}.yaml"), load_system_config())
    )
    topology.infer_missing_collectors()
    errors = topology.check()
    assert errors == [], f"{name}: check() вернул ошибки:\n  " + "\n  ".join(errors)


def test_beta_camera_readiness_makes_stopping_block_start() -> None:
    """R4-1 (2.2c): ключ readiness β повышает `stopping` камеры с out_of_spec до check_function (блокирует START)."""
    from types import SimpleNamespace

    from multiprocess_framework.modules.process_module.health.readiness_policy import (
        NEVER_CLEAN,
        apply_policy,
        parse_policy,
    )
    from multiprocess_framework.modules.process_module.health.schema import READINESS_BLOCKING_SEVERITIES
    from Services.camera_device.plugin_base import CameraDevicePlugin

    cfg = _camera_nodes("hikvision_letter_robot")["camera_0"][1]
    assert cfg["readiness"] == {"severity": {"out_of_spec": "check_function"}}
    stub = SimpleNamespace(_session=SimpleNamespace(state="stopping"), _reg=SimpleNamespace(auto_start=True))
    items = [(d["severity"], d["reason"]) for d in CameraDevicePlugin.readiness(stub, None)]
    assert [sev for sev, _ in items] == ["out_of_spec"]

    def blocks(policy) -> bool:
        resolved, _ = apply_policy(items, policy, NEVER_CLEAN, 100.0)
        return any(sev in READINESS_BLOCKING_SEVERITIES for sev, _ in resolved)

    assert (blocks(parse_policy(None)), blocks(parse_policy(cfg["readiness"]))) == (False, True)


def test_beta_devices_have_no_reconnect_limit() -> None:
    """R4-1 (решение владельца 2026-11-20): у `robot_main` и `vfd_belt` β лимит переподключения снят (0)."""
    raw = yaml.safe_load((_RECIPES_DIR / "hikvision_letter_robot.yaml").read_text(encoding="utf-8"))
    params = {d["id"]: d["params"] for d in raw["devices"]}
    assert params["robot_main"]["max_reconnect_attempts"] == 0
    assert params["vfd_belt"]["max_reconnect_attempts"] == 0


def _beta_plugin_config(plugin_name: str) -> dict:
    raw = yaml.safe_load((_RECIPES_DIR / "hikvision_letter_robot.yaml").read_text(encoding="utf-8"))
    found = [
        p.get("config", {})
        for proc in raw["blueprint"]["processes"]
        for p in proc.get("plugins", [])
        if p.get("plugin_name") == plugin_name
    ]
    assert len(found) == 1, f"{plugin_name}: узлов {len(found)}"
    return found[0]


def test_beta_uses_homography_not_linear_mode() -> None:
    """R4-2 (владелец 2026-10-25): β без линейного режима — гомография F7; без калибровки β даёт отказ или нули."""
    assert _beta_plugin_config("pixel_to_robot")["use_linear"] is False


def test_beta_word_starts_at_minus_440_like_sim() -> None:
    """R4-2 (владелец 2026-11-20): `first_y` слова β как в сим-рецепте; `last_y` не менялся."""
    cfg = _beta_plugin_config("word_layout")
    assert cfg["first_y"] == -440.0
    assert cfg["last_y"] == 300.0


def test_beta_robot_driver_is_v2_with_beta_address() -> None:
    """R4-3 (владелец 2026-11-20): драйвер β — `delta_v2`; адрес реального робота прежний (не адрес сима)."""
    raw = yaml.safe_load((_RECIPES_DIR / "hikvision_letter_robot.yaml").read_text(encoding="utf-8"))
    robot = next(d for d in raw["devices"] if d["id"] == "robot_main")
    assert robot["protocol"] == "delta_v2"
    transport = robot["transport"]
    assert (transport["host"], transport["port"], transport["unit_id"]) == ("192.168.1.7", 502, 2)
