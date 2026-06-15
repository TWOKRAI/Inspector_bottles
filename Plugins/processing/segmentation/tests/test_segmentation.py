"""Тесты SegmentationPlugin — контракт + graceful passthrough без mediapipe."""

from __future__ import annotations

import numpy as np

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

from Plugins.processing.segmentation.plugin import SegmentationPlugin


def _make_plugin(config: dict | None = None) -> SegmentationPlugin:
    services = MockProcessServices(name="seg", config=config or {})
    ctx = PluginContext(services=services, config=config or {})
    plugin = SegmentationPlugin()
    plugin.configure(ctx)
    return plugin


def test_ports_and_name() -> None:
    assert SegmentationPlugin.name == "segmentation"
    assert {p.name for p in SegmentationPlugin.inputs} == {"frame"}
    assert {p.name for p in SegmentationPlugin.outputs} == {"frame", "mask"}


def test_register_defaults() -> None:
    plugin = _make_plugin()
    assert plugin._reg.threshold == 0.5
    assert plugin._reg.bg_white is True


def test_degraded_frame_has_hint() -> None:
    """Без mediapipe (degraded) — кадр проходит с подсказкой, без краша, та же форма."""
    plugin = _make_plugin()
    plugin._degraded = True  # имитируем отсутствие mediapipe
    frame = np.zeros((64, 200, 3), dtype=np.uint8)
    out = plugin.process([{"frame": frame}])[0]
    assert isinstance(out["frame"], np.ndarray)
    assert out["frame"].shape == frame.shape
    assert int(out["frame"].max()) > 0  # нарисована подсказка (красный текст)


def test_none_frame_dropped() -> None:
    plugin = _make_plugin()
    plugin._degraded = True
    assert plugin.process([{"frame": None}]) == []
