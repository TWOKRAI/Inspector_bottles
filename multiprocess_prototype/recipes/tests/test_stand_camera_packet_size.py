# -*- coding: utf-8 -*-
"""Каждый рецепт, открывающий камеры стенда, задаёт настройки GigE-пакета явно.

DA1689923 после включения питания держала GevSCPSPacketSize 8164, и все повреждённые кадры были
чёрными (docs/reviews/2026-11-26_stand-camera-packet-size.md). Ожидаемые значения — литералы.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from Services.hikvision_camera.plugin.plugin import HikvisionCameraPlugin

_RECIPES_DIR = Path(__file__).resolve().parents[1]
_STAND_SERIALS = {"DA1689923", "DA1689977"}


def _stand_camera_configs(path: Path) -> list[tuple[str, dict[str, Any]]]:
    """(process_name, плоский конфиг плагина как в бою) для плагинов с серийником камеры стенда."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    found: list[tuple[str, dict[str, Any]]] = []
    for proc in (raw.get("blueprint") or {}).get("processes") or []:
        for pdef in proc.get("plugins") or []:
            cfg = PluginOrchestrator._extract_plugin_config(pdef)
            if cfg.get("device_serial") in _STAND_SERIALS:
                found.append((proc["process_name"], cfg))
    return found


def test_stand_cameras_set_packet_settings_explicitly() -> None:
    files: set[str] = set()
    wrong: list[str] = []
    for path in sorted(_RECIPES_DIR.glob("*.yaml")):
        for proc, cfg in _stand_camera_configs(path):
            files.add(path.name)
            got = (cfg.get("packet_managed"), cfg.get("packet_size"), cfg.get("packet_delay"))
            if got[0] is not True or got[1:] != (1500, 400):
                wrong.append(f"{path.name}:{proc} -> {got}")
    assert len(files) >= 9, f"рецептов с камерами стенда найдено меньше 9: {sorted(files)}"
    assert not wrong, "\n".join(wrong)


def test_packet_settings_reach_register() -> None:
    cameras = _stand_camera_configs(_RECIPES_DIR / "hikvision_id3013_quad.yaml")
    assert len(cameras) == 2
    for _, cfg in cameras:
        reg = HikvisionCameraPlugin()._init_register(SimpleNamespace(config=cfg, registers=None))
        assert reg.packet_managed is True
        assert reg.packet_size == 1500
        assert reg.packet_delay == 400
