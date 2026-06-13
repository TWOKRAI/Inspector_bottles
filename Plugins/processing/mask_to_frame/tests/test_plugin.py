"""Тесты MaskToFramePlugin: маска (1ch) → BGR-кадр для дисплея."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from Plugins.processing.mask_to_frame.plugin import MaskToFramePlugin


def _ctx(config: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.config = config or {}
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    return ctx


def _plugin(config: dict | None = None) -> MaskToFramePlugin:
    p = MaskToFramePlugin()
    p.configure(_ctx(config))
    return p


def test_no_mask_skipped():
    assert _plugin().process([{"frame": np.zeros((10, 10, 3), np.uint8)}]) == []


def test_mask_2d_to_bgr():
    p = _plugin()
    mask = np.zeros((40, 40), dtype=np.uint8)
    mask[10:30, 10:30] = 255
    out = p.process([{"mask": mask}])
    assert len(out) == 1
    frame = out[0]["frame"]
    assert frame.shape == (40, 40, 3)  # стал 3-канальным
    assert int(frame[20, 20, 0]) == 255 and int(frame[20, 20, 2]) == 255  # белый из маски


def test_custom_source_key():
    p = _plugin({"source_key": "white"})
    mask = np.full((20, 20), 255, dtype=np.uint8)
    out = p.process([{"white": mask}])
    assert out[0]["frame"].shape == (20, 20, 3)
