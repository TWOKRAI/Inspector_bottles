"""Тесты CircleDrawPlugin: рисует окружности из detections на копии кадра."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from Plugins.render.circle_draw.plugin import CircleDrawPlugin


def _ctx(config: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.config = config or {}
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    return ctx


def _plugin(config: dict | None = None) -> CircleDrawPlugin:
    p = CircleDrawPlugin()
    p.configure(_ctx(config))
    return p


def test_no_frame_skipped():
    assert _plugin().process([{"detections": [{"center": [10, 10], "radius": 5}]}]) == []


def test_no_detections_passthrough_unchanged():
    p = _plugin()
    frame = np.zeros((50, 50, 3), dtype=np.uint8)
    out = p.process([{"frame": frame, "detections": []}])
    assert len(out) == 1
    # без детекций кадр не трогаем (тот же объект)
    assert out[0]["frame"] is frame


def test_draws_circle_on_copy():
    p = _plugin({"color_bgr": [0, 255, 0], "thickness": 2, "draw_center": False})
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    out = p.process([{"frame": frame, "detections": [{"center": [50, 50], "radius": 20}]}])
    canvas = out[0]["frame"]
    # оригинал не тронут, на копии появилась зелёная окружность
    assert int(frame.sum()) == 0
    assert int(canvas[:, :, 1].sum()) > 0  # есть зелёный
    assert int(canvas[:, :, 0].sum()) == 0  # синего нет


def test_skips_detection_without_radius():
    p = _plugin()
    frame = np.zeros((60, 60, 3), dtype=np.uint8)
    out = p.process([{"frame": frame, "detections": [{"center": [30, 30]}]}])
    assert int(out[0]["frame"].sum()) == 0  # ничего не нарисовано
