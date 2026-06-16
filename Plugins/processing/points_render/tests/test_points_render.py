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


def test_render_sheet_with_bounds_no_points() -> None:
    # Лист (прямоугольник+углы+подписи) рисуется даже без точек, если заданы bounds.
    out = geometry.render_points([], 320, 240, bounds=(0.0, 0.0, 192.0, 144.0), bg_white=True, show_sheet=True)
    assert out.shape == (240, 320, 3)
    assert int(out.min()) < 255  # появились пиксели листа/подписей


def test_render_sheet_disabled() -> None:
    # show_sheet=False и нет точек → холст чистый, несмотря на bounds.
    out = geometry.render_points([], 320, 240, bounds=(0.0, 0.0, 192.0, 144.0), bg_white=True, show_sheet=False)
    assert int(out.mean()) == 255


def test_ordered_corners_lv_top_left() -> None:
    # bounds = упорядоченные углы [x0,y0(ЛВ), x1,y1(ПН)]: точка у ЛВ → верх-лево холста.
    pts = [{"x_mm": 0.0, "y_mm": 0.0, "pen": 1}]  # = ЛВ (x0,y0)
    out = geometry.render_points(pts, 200, 200, bounds=(0.0, 0.0, 100.0, 100.0), show_sheet=False, dot_radius=5)
    ys, xs = _green_yx(out)
    assert ys.mean() < 100 and xs.mean() < 100  # верх-лево


def test_flip_y_mirrors_points() -> None:
    # flip_y переворачивает рисунок по вертикали: ЛВ-точка уходит вниз.
    pts = [{"x_mm": 0.0, "y_mm": 0.0, "pen": 1}]
    out = geometry.render_points(
        pts, 200, 200, bounds=(0.0, 0.0, 100.0, 100.0), show_sheet=False, dot_radius=5, flip_y=True
    )
    ys, _ = _green_yx(out)
    assert ys.mean() > 100  # с flip — точка у низа


def test_swap_axes_shows_upright() -> None:
    # Лист повёрнут 90° (swap): точка у ВЛ-угла (x0,y0) → верх-лево экрана (портрет ровно).
    pts = [{"x_mm": 325.0, "y_mm": -223.0, "pen": 1}]  # ВЛ
    out = geometry.render_points(
        pts, 200, 200, bounds=(325.0, -223.0, 544.0, -17.0), swap_axes=True, show_sheet=False, dot_radius=5
    )
    ys, xs = _green_yx(out)
    assert ys.mean() < 100 and xs.mean() < 100  # верх-лево (ровно)


def _green_yx(img: np.ndarray):
    mask = (img[:, :, 1] > 100) & (img[:, :, 0] < 100) & (img[:, :, 2] < 100)
    ys, xs = np.where(mask)
    return ys, xs


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
