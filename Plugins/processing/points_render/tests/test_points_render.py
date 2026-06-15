"""Тесты PointsRenderPlugin и рендера карты точек."""

from __future__ import annotations

import numpy as np

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

from Plugins.processing.points_render import geometry
from Plugins.processing.points_render.plugin import PointsRenderPlugin


def _make_plugin(config: dict | None = None) -> PointsRenderPlugin:
    services = MockProcessServices(name="points", config=config or {})
    ctx = PluginContext(services=services, config=config or {})
    plugin = PointsRenderPlugin()
    plugin.configure(ctx)
    return plugin


# --- geometry ---


def test_render_empty_returns_blank_canvas() -> None:
    out = geometry.render_points([], 320, 240, bg_white=True)
    assert out.shape == (240, 320, 3)
    assert int(out.mean()) == 255  # белый холст


def test_render_draws_on_canvas() -> None:
    points = [
        {"x_mm": 0.0, "y_mm": 0.0, "pen": 0},
        {"x_mm": 10.0, "y_mm": 0.0, "pen": 1},
        {"x_mm": 10.0, "y_mm": 10.0, "pen": 1},
    ]
    out = geometry.render_points(points, 320, 240, bg_white=True)
    # На белом холсте появились не-белые пиксели (точки/путь)
    assert int(out.min()) < 255


# --- plugin ---


def test_plugin_replaces_frame_with_canvas() -> None:
    plugin = _make_plugin({"canvas_width": 200, "canvas_height": 150})
    points = [{"x_mm": 1.0, "y_mm": 2.0, "pen": 0}, {"x_mm": 3.0, "y_mm": 4.0, "pen": 1}]
    out = plugin.process([{"frame": "OLD", "draw_points": points}])[0]
    assert isinstance(out["frame"], np.ndarray)
    assert out["frame"].shape == (150, 200, 3)
    assert out["draw_points"] == points  # pass-through
    assert plugin._reg.points_last == 2


def test_plugin_no_points_blank() -> None:
    plugin = _make_plugin({"canvas_width": 100, "canvas_height": 100})
    out = plugin.process([{"frame": "OLD"}])[0]
    assert out["frame"].shape == (100, 100, 3)
    assert plugin._reg.points_last == 0
