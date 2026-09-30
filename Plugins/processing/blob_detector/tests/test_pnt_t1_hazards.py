"""pipeline-node-timing T1: hazard-тесты автора механизма (маска сверху + рисование на копии)."""

from __future__ import annotations

from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from Plugins.processing.blob_detector.plugin import BlobDetectorPlugin


def _plugin(**cfg) -> BlobDetectorPlugin:
    """Детектор белых областей на чёрном кадре."""
    base = {
        "s_min": 0,
        "s_max": 255,
        "v_min": 200,
        "v_max": 255,
        "h_min": 0,
        "h_max": 180,
        "min_area": 10,
        "max_area": 0,
        "draw_contours": False,
    }
    base.update(cfg)
    ctx = MagicMock()
    ctx.config = base
    plugin = BlobDetectorPlugin()
    plugin.configure(ctx)
    return plugin


def _frame_with_white_square() -> np.ndarray:
    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    cv2.rectangle(frame, (50, 50), (100, 100), (255, 255, 255), -1)
    return frame


@pytest.mark.parametrize(
    "bad_mask",
    [
        np.full((200, 200), 255, dtype=bool),  # bool
        np.full((200, 200), 255, dtype=np.int32),  # int32
        np.full((200, 200, 3), 255, dtype=np.uint8),  # 3 канала
    ],
    ids=["bool", "int32", "3ch"],
)
def test_bad_upstream_mask_falls_back_to_own_thresholding(bad_mask):
    """Негодная маска (dtype/каналы) не используется и не роняет: детектор порогует сам -> 1 квадрат.

    Если бы негодную маску приняли, «всё белое» дало бы один контур на весь кадр
    (bbox 0..200), а не квадрат 50..100 — поэтому проверяем bbox.
    """
    result = _plugin().process([{"frame": _frame_with_white_square(), "mask": bad_mask}])

    dets = result[0]["detections"]
    assert len(dets) == 1
    assert dets[0]["bbox"] == [50, 50, 101, 101]


def _warning_count(plugin: BlobDetectorPlugin) -> int:
    return plugin._ctx.log_warning.call_count


def test_rejected_mask_warns_exactly_once_over_many_frames():
    """Маска от другого разрешения (после resize) отвергается молча раньше: 10 кадров -> ровно 1 предупреждение."""
    plugin = _plugin()
    half_mask = np.full((100, 100), 255, dtype=np.uint8)

    for _ in range(10):
        plugin.process([{"frame": _frame_with_white_square(), "mask": half_mask}])

    assert _warning_count(plugin) == 1
    msg = plugin._ctx.log_warning.call_args[0][0]
    assert "(100, 100)" in msg and "(200, 200)" in msg  # обе формы названы


def test_bool_dtype_mask_warns_exactly_once():
    plugin = _plugin()
    bool_mask = np.full((200, 200), True, dtype=bool)

    plugin.process([{"frame": _frame_with_white_square(), "mask": bool_mask}])
    plugin.process([{"frame": _frame_with_white_square(), "mask": bool_mask}])

    assert _warning_count(plugin) == 1
    assert "bool" in plugin._ctx.log_warning.call_args[0][0]


def test_no_mask_does_not_warn():
    plugin = _plugin()

    plugin.process([{"frame": _frame_with_white_square()}])
    plugin.process([{"frame": _frame_with_white_square(), "mask": None}])

    assert _warning_count(plugin) == 0


def test_valid_mask_does_not_warn():
    plugin = _plugin()
    good_mask = np.zeros((200, 200), dtype=np.uint8)

    plugin.process([{"frame": _frame_with_white_square(), "mask": good_mask}])

    assert _warning_count(plugin) == 0


def test_draw_contours_returns_new_frame_with_contours_and_keeps_input():
    """draw_contours: выходной frame — другой объект с нарисованными контурами, вход не тронут."""
    frame = _frame_with_white_square()
    before = frame.copy()

    result = _plugin(draw_contours=True, contour_color_bgr=[0, 0, 255]).process([{"frame": frame}])
    out = result[0]["frame"]

    assert out is not frame
    assert np.array_equal(frame, before)
    assert not np.array_equal(out, before)
    assert (out[50, 50] == [0, 0, 255]).all()  # угол квадрата закрашен цветом контура
