"""Тесты StrokesToPointsPlugin — непрерывный расчёт draw_points и формат точек."""

from __future__ import annotations

import numpy as np

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

from Plugins.processing.strokes_to_points.plugin import StrokesToPointsPlugin


def _make_plugin(config: dict | None = None) -> StrokesToPointsPlugin:
    services = MockProcessServices(name="lines", config=config or {})
    ctx = PluginContext(services=services, config=config or {})
    plugin = StrokesToPointsPlugin()
    plugin.configure(ctx)
    return plugin


def _square_mask() -> np.ndarray:
    """Рамка-квадрат (линия, не заливка) — корректна для centerline-режима."""
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[20:80, 20:23] = 255
    mask[20:80, 77:80] = 255
    mask[20:23, 20:80] = 255
    mask[77:80, 20:80] = 255
    return mask


def test_computes_points_every_frame() -> None:
    plugin = _make_plugin({"min_stroke_len": 5.0})
    out = plugin.process([{"frame": "F", "mask": _square_mask()}])[0]
    assert "draw_points" in out
    pts = out["draw_points"]
    assert isinstance(pts, list) and len(pts) >= 2
    assert all({"x_mm", "y_mm", "pen"} <= set(p) for p in pts)
    assert pts[0]["pen"] == 0  # первый — подвод
    # На следующем кадре снова считается (не one-shot)
    out2 = plugin.process([{"frame": "F", "mask": _square_mask()}])[0]
    assert "draw_points" in out2


def test_passthrough_without_mask() -> None:
    plugin = _make_plugin({"min_stroke_len": 5.0})
    out = plugin.process([{"frame": "F"}])[0]
    assert "draw_points" not in out
    assert out["frame"] == "F"


def test_counters_updated() -> None:
    plugin = _make_plugin({"min_stroke_len": 5.0})
    plugin.process([{"mask": _square_mask()}])
    assert plugin._reg.points_last >= 2
    assert plugin._reg.strokes_last >= 1


def test_no_commands() -> None:
    assert StrokesToPointsPlugin.commands == {}


def test_cache_reused_on_identical_mask() -> None:
    """Та же маска и параметры → результат берётся из кэша (без пересчёта)."""
    plugin = _make_plugin({"min_stroke_len": 5.0})
    mask = _square_mask()
    out1 = plugin.process([{"mask": mask}])[0]
    # Другой объект той же формы/содержимого — кэш обязан сработать.
    out2 = plugin.process([{"mask": mask.copy()}])[0]
    assert out2["draw_points"] is out1["draw_points"]  # тот же list из кэша
    assert out2["draw_bounds"] == out1["draw_bounds"]


def test_cache_invalidated_on_param_change() -> None:
    """Смена register-параметра (live-тюнинг) → кэш сбрасывается, идёт пересчёт."""
    plugin = _make_plugin({"min_stroke_len": 5.0, "simplify_epsilon": 0.0})
    mask = _square_mask()
    out1 = plugin.process([{"mask": mask}])[0]
    plugin._reg.simplify_epsilon = 5.0  # сильнее прореживание → меньше точек
    out2 = plugin.process([{"mask": mask}])[0]
    assert out2["draw_points"] is not out1["draw_points"]
    assert len(out2["draw_points"]) <= len(out1["draw_points"])


def test_cache_invalidated_on_mask_change() -> None:
    """Другая маска → пересчёт, а не устаревший кэш."""
    plugin = _make_plugin({"min_stroke_len": 5.0})
    out1 = plugin.process([{"mask": _square_mask()}])[0]
    other = np.zeros((100, 100), dtype=np.uint8)
    other[10:90, 50:53] = 255  # одна вертикальная линия
    out2 = plugin.process([{"mask": other}])[0]
    assert out2["draw_points"] is not out1["draw_points"]
