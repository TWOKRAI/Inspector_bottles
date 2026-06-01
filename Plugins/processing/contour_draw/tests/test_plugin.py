"""Тесты ContourDrawPlugin — рисование контура на копии кадра."""

from __future__ import annotations

import numpy as np

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

from Plugins.processing.contour_draw.plugin import ContourDrawPlugin


def _make_plugin(config: dict | None = None) -> ContourDrawPlugin:
    services = MockProcessServices(name="draw_proc", config=config or {})
    ctx = PluginContext(services=services, config=config or {})
    plugin = ContourDrawPlugin()
    plugin.configure(ctx)
    return plugin


def _square_contour() -> np.ndarray:
    """Контур-квадрат (cv2 формат (N,1,2) int32)."""
    return np.array([[[30, 30]], [[30, 70]], [[70, 70]], [[70, 30]]], dtype=np.int32)


def test_draws_on_copy_not_original() -> None:
    plugin = _make_plugin({"color_b": 255, "color_g": 0, "color_r": 0, "thickness": 2})
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    out = plugin.process([{"frame": frame, "contours": [_square_contour()]}])[0]
    # Оригинал не тронут
    assert int(np.count_nonzero(frame)) == 0
    # На выходе появились синие пиксели (B=255)
    drawn = out["frame"]
    assert int(np.count_nonzero(drawn)) > 0
    assert drawn[30, 30, 0] == 255  # B-канал линии


def test_no_contours_passthrough() -> None:
    plugin = _make_plugin()
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    item = {"frame": frame, "contours": []}
    out = plugin.process([item])[0]
    assert out is item  # без контуров — тот же item


def test_missing_contours_key_passthrough() -> None:
    plugin = _make_plugin()
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    out = plugin.process([{"frame": frame}])[0]
    assert np.array_equal(out["frame"], frame)


def test_none_frame_skipped() -> None:
    plugin = _make_plugin()
    assert plugin.process([{"frame": None, "contours": [_square_contour()]}]) == []
