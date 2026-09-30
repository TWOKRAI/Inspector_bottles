"""pipeline-node-timing T1: guard — контуры рисует render_overlay, blob_detector кадр не копирует.

blob_detector с draw_contours=True копирует кадр 1080p (~1 мс) на каждом кадре; детекции
и так рисует render_overlay (draw_detections). Тест ловит возврат draw_contours в YAML.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

TOPOLOGY_DIR = Path(__file__).resolve().parents[1]


def _plugin_cfg(topology: dict, plugin_name: str) -> dict:
    found = [
        p for proc in topology["processes"] for p in proc.get("plugins", []) if p.get("plugin_name") == plugin_name
    ]
    assert len(found) == 1, f"ожидали ровно один плагин {plugin_name}, нашли {len(found)}"
    return found[0]


@pytest.mark.parametrize("yaml_name", ["inspection_full.yaml", "inspection_basic.yaml"])
def test_blob_detector_does_not_draw_render_overlay_does(yaml_name):
    with open(TOPOLOGY_DIR / yaml_name, encoding="utf-8") as f:
        topology = yaml.safe_load(f)

    assert _plugin_cfg(topology, "blob_detector")["draw_contours"] is False
    assert _plugin_cfg(topology, "render_overlay")["draw_detections"] is True
