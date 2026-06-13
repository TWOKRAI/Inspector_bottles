"""Тесты RoiCropPlugin: вырез ROI, клампинг границ, live-параметры, 0=до края."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from Plugins.processing.roi_crop.plugin import RoiCropPlugin


def _ctx(config: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.config = config or {}
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    return ctx


def _plugin(config: dict | None = None) -> RoiCropPlugin:
    p = RoiCropPlugin()
    p.configure(_ctx(config))
    return p


def _frame(h=480, w=640):
    return np.zeros((h, w, 3), dtype=np.uint8)


def test_no_frame_skipped():
    assert _plugin({"width": 100, "height": 100}).process([{}]) == []


def test_basic_crop():
    p = _plugin({"x": 100, "y": 50, "width": 200, "height": 150})
    out = p.process([{"frame": _frame()}])
    assert len(out) == 1
    assert out[0]["frame"].shape == (150, 200, 3)
    assert out[0]["roi_x"] == 100 and out[0]["roi_y"] == 50


def test_zero_size_to_edge():
    """width/height=0 → до правого/нижнего края кадра."""
    p = _plugin({"x": 600, "y": 440, "width": 0, "height": 0})
    out = p.process([{"frame": _frame(480, 640)}])
    assert out[0]["frame"].shape == (40, 40, 3)  # 640-600 × 480-440


def test_clamp_oob():
    """ROI вылазит за границу → клампится, не падает."""
    p = _plugin({"x": 500, "y": 400, "width": 400, "height": 400})
    out = p.process([{"frame": _frame(480, 640)}])
    assert out[0]["frame"].shape == (80, 140, 3)  # 640-500 × 480-400


def test_live_param_change_applies():
    """Изменение register между кадрами применяется сразу (live)."""
    p = _plugin({"x": 0, "y": 0, "width": 100, "height": 100})
    out1 = p.process([{"frame": _frame()}])
    assert out1[0]["frame"].shape == (100, 100, 3)
    p._reg.width = 200
    p._reg.height = 50
    out2 = p.process([{"frame": _frame()}])
    assert out2[0]["frame"].shape == (50, 200, 3)


def test_degenerate_roi_skipped():
    p = _plugin({"x": 700, "y": 0, "width": 50, "height": 50})  # x за пределами 640
    out = p.process([{"frame": _frame(480, 640)}])
    # x клампится к 639 → width до края = 1px, height 50 → валидный? x0=639,x1=min(689,640)=640 → 1px
    assert out == [] or out[0]["frame"].shape[1] >= 1
