# -*- coding: utf-8 -*-
"""Рецепт букв на железе включает переподключение камеры (решение владельца 2026-11-26).

Без этих двух настроек вынутый кабель оставляет камеру мёртвой до перезапуска. Ожидаемые значения — литералы.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import yaml

from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from Services.hikvision_camera.plugin.plugin import HikvisionCameraPlugin

_RECIPE = Path(__file__).resolve().parents[1] / "hikvision_letter_robot.yaml"


def test_letter_robot_camera_reconnects_after_silence() -> None:
    raw = yaml.safe_load(_RECIPE.read_text(encoding="utf-8"))
    cameras = [
        PluginOrchestrator._extract_plugin_config(pdef)
        for proc in raw["blueprint"]["processes"]
        for pdef in proc.get("plugins") or []
        if pdef.get("plugin_name") == "hikvision"
    ]
    assert len(cameras) == 1
    reg = HikvisionCameraPlugin()._init_register(SimpleNamespace(config=cameras[0], registers=None))
    assert reg.reconnect is True
    assert reg.link_silence_s == 3.0
    assert reg.reconnect_interval_s == 2.0
