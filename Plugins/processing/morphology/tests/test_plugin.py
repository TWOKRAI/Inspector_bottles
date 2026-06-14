"""Тесты MorphologyPlugin — морфологическая чистка бинарной маски."""

from __future__ import annotations

import cv2
import numpy as np

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

from Plugins.processing.morphology.plugin import MorphologyPlugin


def _make_plugin(config: dict | None = None) -> MorphologyPlugin:
    services = MockProcessServices(name="morph_proc", config=config or {})
    ctx = PluginContext(services=services, config=config or {})
    plugin = MorphologyPlugin()
    plugin.configure(ctx)
    return plugin


def _mask_with_noise() -> np.ndarray:
    """Маска 100x100: сплошной круг r=12 в центре + одиночные пиксели-шум."""
    mask = np.zeros((100, 100), dtype=np.uint8)
    cv2.circle(mask, (50, 50), 12, 255, -1)
    rng = np.random.default_rng(0)
    for _ in range(50):
        y, x = int(rng.integers(0, 100)), int(rng.integers(0, 100))
        if abs(x - 50) > 20 or abs(y - 50) > 20:  # шум вне круга
            mask[y, x] = 255
    return mask


def _count_blobs(mask: np.ndarray) -> int:
    return len(cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0])


def test_open_close_removes_speckle_noise_keeps_blob() -> None:
    plugin = _make_plugin({"operation": "open_close", "kernel_size": 5})
    mask = _mask_with_noise()
    assert _count_blobs(mask) > 1  # есть шум
    out = plugin.process([{"frame": None, "mask": mask}])[0]
    # Остался ровно один сплошной круг — шум вычищен
    assert _count_blobs(out["mask"]) == 1
    # Центр круга цел
    assert out["mask"][50, 50] == 255


def test_none_is_passthrough() -> None:
    plugin = _make_plugin({"operation": "none"})
    mask = _mask_with_noise()
    out = plugin.process([{"mask": mask}])[0]
    assert np.array_equal(out["mask"], mask)


def test_missing_mask_passthrough() -> None:
    plugin = _make_plugin()
    out = plugin.process([{"frame": "X", "frame_id": 7}])[0]
    assert out == {"frame": "X", "frame_id": 7}
    assert "mask" not in out


def test_frame_not_mutated() -> None:
    plugin = _make_plugin({"operation": "open_close"})
    frame = np.full((100, 100, 3), 123, dtype=np.uint8)
    out = plugin.process([{"frame": frame, "mask": _mask_with_noise()}])[0]
    assert out["frame"] is frame  # кадр проброшен без копий


def test_dilate_grows_blob() -> None:
    plugin = _make_plugin({"operation": "dilate", "kernel_size": 5, "iterations": 2})
    mask = np.zeros((100, 100), dtype=np.uint8)
    cv2.circle(mask, (50, 50), 10, 255, -1)
    before = int(np.count_nonzero(mask))
    out = plugin.process([{"mask": mask}])[0]
    assert int(np.count_nonzero(out["mask"])) > before
