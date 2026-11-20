# -*- coding: utf-8 -*-
"""Task 4c: ключ ``run_locked_commands`` лежит в рецепте ``camera_device_demo`` там, где его прочтёт плагин.

Ключ читается из ``ctx.config`` плагина (``PluginOrchestrator._extract_plugin_config`` — путь боя); на уровне
узла процесса он молча игнорируется, поэтому тест проверяет и место, и состав списка.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from Services.camera_device.plugin_base import CameraDevicePlugin

_RECIPE_FILE = Path(__file__).resolve().parent.parent / "camera_device_demo.yaml"
_EXPECTED = ["release_device", "take_device"]


def _load_blueprint() -> dict:
    return yaml.safe_load(_RECIPE_FILE.read_text(encoding="utf-8"))["blueprint"]


def _cam_fake_node(blueprint: dict) -> dict:
    nodes = [p for p in blueprint["processes"] if p.get("process_name") == "cam_fake"]
    assert len(nodes) == 1, f"ожидался ровно один узел cam_fake, найдено {len(nodes)}"
    return nodes[0]


def _camera_pdef(node: dict) -> dict:
    pdefs = [p for p in node["plugins"] if p.get("plugin_name") == "camera_device"]
    assert len(pdefs) == 1, f"ожидался ровно один плагин camera_device в cam_fake, найдено {len(pdefs)}"
    return pdefs[0]


def test_run_locked_commands_reach_plugin_config() -> None:
    config = PluginOrchestrator._extract_plugin_config(_camera_pdef(_cam_fake_node(_load_blueprint())))
    assert config["run_locked_commands"] == _EXPECTED


def test_every_locked_command_is_a_plugin_command() -> None:
    config = PluginOrchestrator._extract_plugin_config(_camera_pdef(_cam_fake_node(_load_blueprint())))
    for name in config["run_locked_commands"]:
        assert name in CameraDevicePlugin.commands, name


def test_key_is_not_on_process_node_level() -> None:
    assert "run_locked_commands" not in _cam_fake_node(_load_blueprint())
