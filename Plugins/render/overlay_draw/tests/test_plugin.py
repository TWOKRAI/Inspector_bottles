"""Тесты OverlayDrawPlugin: рендер vline/точек, резолв цвета, edge-cases."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from Plugins.render.overlay_draw.plugin import OverlayDrawPlugin
from Plugins.render.overlay_draw.config import OverlayDrawConfig


def _make_plugin(**reg_overrides) -> OverlayDrawPlugin:
    p = OverlayDrawPlugin()
    ctx = MagicMock()
    ctx.registers = None
    ctx.config = reg_overrides
    ctx.log_info = MagicMock()
    p.configure(ctx)
    return p


def _frame(h=480, w=640, val=0) -> np.ndarray:
    return np.full((h, w, 3), val, dtype=np.uint8)


class TestConfig:
    def test_defaults(self):
        cfg = OverlayDrawConfig()
        assert "OverlayDrawPlugin" in cfg.plugin_class


class TestRender:
    def test_no_frame_returns_none(self):
        p = _make_plugin()
        out = p.process([{"overlay": {"points": [{"xy": [10, 10]}]}}])
        assert out == []  # @for_each отфильтровал item без frame

    def test_empty_overlay_keeps_frame(self):
        p = _make_plugin()
        f = _frame(val=50)
        out = p.process([{"frame": f, "overlay": {}}])
        assert "rendered_frame" in out[0]
        assert np.array_equal(out[0]["rendered_frame"], f)

    def test_vline_draws_pixels(self):
        """vline рисует непустую линию на кадре."""
        p = _make_plugin()
        f = _frame()
        overlay = {"vlines": [{"cx": 320, "cy": 240, "angle": 0, "zone_width": 60}]}
        out = p.process([{"frame": f, "overlay": overlay}])
        rendered = out[0]["rendered_frame"]
        assert not np.array_equal(rendered, f)  # что-то нарисовано
        # Центральная линия y=240 жёлтая (BGR 0,255,255 по умолчанию).
        assert tuple(rendered[240, 320]) != (0, 0, 0)

    def test_point_drawn(self):
        p = _make_plugin()
        f = _frame()
        out = p.process([{"frame": f, "overlay": {"points": [{"xy": [100, 100]}]}}])
        rendered = out[0]["rendered_frame"]
        assert tuple(rendered[100, 100]) != (0, 0, 0)

    def test_frame_not_mutated(self):
        """Исходный кадр не меняется (рисуем на копии)."""
        p = _make_plugin()
        f = _frame()
        f_copy = f.copy()
        p.process([{"frame": f, "overlay": {"points": [{"xy": [100, 100]}]}}])
        assert np.array_equal(f, f_copy)


class TestColorResolution:
    def test_per_shape_color_wins(self):
        p = _make_plugin()
        f = _frame()
        # явный синий цвет точки (BGR 255,0,0)
        out = p.process([{"frame": f, "overlay": {"points": [{"xy": [50, 50], "color": [255, 0, 0]}]}}])
        assert tuple(out[0]["rendered_frame"][50, 50]) == (255, 0, 0)

    def test_group_color_resolved(self):
        """Цвет по group из color_table перебивает type."""
        p = _make_plugin(
            color_table=[
                {"type": "point", "color": [0, 0, 255]},
                {"group": "g1", "color": [255, 0, 0]},
            ]
        )
        f = _frame()
        out = p.process([{"frame": f, "overlay": {"points": [{"xy": [50, 50], "group": "g1"}]}}])
        assert tuple(out[0]["rendered_frame"][50, 50]) == (255, 0, 0)

    def test_type_color_default(self):
        """Без group/explicit — цвет по type из таблицы."""
        p = _make_plugin(color_table=[{"type": "point", "color": [10, 20, 30]}])
        f = _frame()
        out = p.process([{"frame": f, "overlay": {"points": [{"xy": [50, 50], "type": "point"}]}}])
        assert tuple(out[0]["rendered_frame"][50, 50]) == (10, 20, 30)
