"""Тесты ContourFinderPlugin — контуры/площадь по маске, mask дропается."""

from __future__ import annotations

import numpy as np

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

from Plugins.processing.contour_finder.plugin import ContourFinderPlugin


def _make_plugin(config: dict | None = None) -> ContourFinderPlugin:
    services = MockProcessServices(name="contour_proc", config=config or {})
    ctx = PluginContext(services=services, config=config or {})
    plugin = ContourFinderPlugin()
    plugin.configure(ctx)
    return plugin


def _mask_with_square(x0: int, y0: int, side: int, size: int = 100) -> np.ndarray:
    """Бинарная маска size×size с белым квадратом side×side."""
    mask = np.zeros((size, size), dtype=np.uint8)
    mask[y0 : y0 + side, x0 : x0 + side] = 255
    return mask


def test_finds_square_with_area_and_bbox() -> None:
    plugin = _make_plugin({"min_area": 50})
    mask = _mask_with_square(30, 30, 40)  # площадь ≈ 39*39 (контур по краю)
    out = plugin.process([{"frame": "FRAME", "mask": mask}])[0]
    dets = out["detections"]
    assert len(dets) == 1
    d = dets[0]
    assert d["area"] >= 1000
    # bbox охватывает квадрат
    assert d["bbox"][0] <= 31 and d["bbox"][1] <= 31
    assert d["bbox"][2] >= 68 and d["bbox"][3] >= 68
    # center близко к (50,50)
    assert abs(d["center"][0] - 50) <= 2 and abs(d["center"][1] - 50) <= 2


def test_mask_dropped_frame_kept() -> None:
    plugin = _make_plugin()
    out = plugin.process([{"frame": "FRAME", "mask": _mask_with_square(30, 30, 40)}])[0]
    assert "mask" not in out  # маска не идёт дальше
    assert out["frame"] == "FRAME"
    assert "contours" in out and len(out["contours"]) == 1


def test_min_area_filters_small() -> None:
    plugin = _make_plugin({"min_area": 5000})
    out = plugin.process([{"mask": _mask_with_square(30, 30, 40)}])[0]  # площадь ~1500 < 5000
    assert out["detections"] == []
    assert out["contours"] == []


def test_max_area_filters_large() -> None:
    plugin = _make_plugin({"min_area": 0, "max_area": 100})
    out = plugin.process([{"mask": _mask_with_square(10, 10, 80)}])[0]  # большая площадь
    assert out["detections"] == []


def test_two_blobs() -> None:
    plugin = _make_plugin({"min_area": 50})
    mask = _mask_with_square(5, 5, 20)
    mask[60:85, 60:85] = 255  # второй квадрат
    out = plugin.process([{"mask": mask}])[0]
    assert len(out["detections"]) == 2


def test_no_mask_passthrough() -> None:
    plugin = _make_plugin()
    out = plugin.process([{"frame": "FRAME"}])[0]
    assert out == {"frame": "FRAME"}  # нет маски — без изменений
