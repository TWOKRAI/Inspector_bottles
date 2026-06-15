"""Тесты BlobFilterPlugin — фильтр связных областей по площади."""

from __future__ import annotations

import numpy as np

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

from Plugins.processing.blob_filter.plugin import BlobFilterPlugin


def _make_plugin(config: dict | None = None) -> BlobFilterPlugin:
    services = MockProcessServices(name="blob_proc", config=config or {})
    ctx = PluginContext(services=services, config=config or {})
    plugin = BlobFilterPlugin()
    plugin.configure(ctx)
    return plugin


def _mask_two_blobs() -> np.ndarray:
    """100×100: маленький blob 10×10 (=100px) и большой 40×40 (=1600px)."""
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[5:15, 5:15] = 255  # маленький
    mask[40:80, 40:80] = 255  # большой
    return mask


def test_min_area_removes_small_blob() -> None:
    plugin = _make_plugin({"min_area": 500})
    out = plugin.process([{"mask": _mask_two_blobs()}])[0]
    result = out["mask"]
    # Маленький blob стёрт, большой остался
    assert result[10, 10] == 0
    assert result[60, 60] == 255


def test_keeps_both_when_min_area_low() -> None:
    plugin = _make_plugin({"min_area": 10})
    out = plugin.process([{"mask": _mask_two_blobs()}])[0]
    result = out["mask"]
    assert result[10, 10] == 255
    assert result[60, 60] == 255


def test_max_area_removes_large_blob() -> None:
    plugin = _make_plugin({"min_area": 0, "max_area": 500})
    out = plugin.process([{"mask": _mask_two_blobs()}])[0]
    result = out["mask"]
    assert result[60, 60] == 0  # большой стёрт
    assert result[10, 10] == 255  # маленький остался


def test_outputs_bgr_frame() -> None:
    plugin = _make_plugin({"min_area": 10})
    out = plugin.process([{"mask": _mask_two_blobs()}])[0]
    frame = out["frame"]
    assert frame.ndim == 3 and frame.shape[2] == 3


def test_passthrough_without_mask() -> None:
    plugin = _make_plugin()
    out = plugin.process([{"frame": "F"}])[0]
    assert out["frame"] == "F"
