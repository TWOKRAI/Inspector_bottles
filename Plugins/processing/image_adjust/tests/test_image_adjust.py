"""Тесты ImageAdjustPlugin и коррекции изображения."""

from __future__ import annotations

import numpy as np

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

from Plugins.processing.image_adjust import geometry
from Plugins.processing.image_adjust.plugin import ImageAdjustPlugin


def _make_plugin(config: dict | None = None) -> ImageAdjustPlugin:
    services = MockProcessServices(name="adj", config=config or {})
    ctx = PluginContext(services=services, config=config or {})
    plugin = ImageAdjustPlugin()
    plugin.configure(ctx)
    return plugin


# --- geometry ---


def test_identity_no_change() -> None:
    frame = np.full((16, 16, 3), 100, dtype=np.uint8)
    out = geometry.apply_adjust(frame)
    assert np.array_equal(out, frame)


def test_brightness_increases() -> None:
    frame = np.full((8, 8, 3), 100, dtype=np.uint8)
    out = geometry.apply_adjust(frame, brightness=40)
    assert int(out.mean()) > 130


def test_contrast_spreads() -> None:
    frame = np.full((8, 8, 3), 200, dtype=np.uint8)  # светлее середины
    out = geometry.apply_adjust(frame, contrast=2.0)
    assert int(out.mean()) > 200  # отодвигается от 127.5 вверх


def test_saturation_grayscale_unchanged_hue() -> None:
    # Серый кадр: насыщенность не создаёт цвета (S=0 остаётся 0)
    frame = np.full((8, 8, 3), 120, dtype=np.uint8)
    out = geometry.apply_adjust(frame, saturation=2.0)
    assert abs(int(out.max()) - int(out.min())) <= 2  # остался серым


def test_clip_no_overflow() -> None:
    frame = np.full((8, 8, 3), 250, dtype=np.uint8)
    out = geometry.apply_adjust(frame, brightness=100, contrast=2.0)
    assert int(out.max()) <= 255 and int(out.min()) >= 0


# --- plugin ---


def test_plugin_adjusts_frame() -> None:
    plugin = _make_plugin({"brightness": 50})
    frame = np.full((8, 8, 3), 100, dtype=np.uint8)
    out = plugin.process([{"frame": frame}])[0]
    assert int(out["frame"].mean()) > 130


def test_plugin_none_dropped() -> None:
    plugin = _make_plugin()
    assert plugin.process([{"frame": None}]) == []
