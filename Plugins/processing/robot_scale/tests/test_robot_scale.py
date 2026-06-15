"""Тесты RobotScalePlugin — вписывание пиксельного пути в прямоугольник листа робота."""

from __future__ import annotations

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

from Plugins.processing.robot_scale.plugin import RobotScalePlugin


def _make_plugin(config: dict | None = None) -> RobotScalePlugin:
    services = MockProcessServices(name="scale", config=config or {})
    ctx = PluginContext(services=services, config=config or {})
    plugin = RobotScalePlugin()
    plugin.configure(ctx)
    return plugin


def test_registered():
    from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry
    import Plugins.processing.robot_scale.plugin  # noqa: F401

    entry = PluginRegistry.get("robot_scale")
    assert entry is not None
    assert entry.category == "processing"


def test_maps_pixels_to_sheet_corners() -> None:
    # Кадр 640x480 → лист (0,0) ЛВ … (200,-200) ПН (робот Y-вверх).
    p = _make_plugin({"src_width": 640, "src_height": 480, "x0": 0.0, "y0": 0.0, "x1": 200.0, "y1": -200.0})
    pts = [
        {"x_mm": 0.0, "y_mm": 0.0, "pen": 1},  # ЛВ угол
        {"x_mm": 320.0, "y_mm": 240.0, "pen": 1},  # центр
        {"x_mm": 640.0, "y_mm": 480.0, "pen": 0},  # ПН угол
    ]
    out = p.process([{"draw_points": pts}])[0]["draw_points"]
    assert out[0] == {"x_mm": 0.0, "y_mm": 0.0, "pen": 1}
    assert out[1] == {"x_mm": 100.0, "y_mm": -100.0, "pen": 1}
    assert out[2] == {"x_mm": 200.0, "y_mm": -200.0, "pen": 0}


def test_updates_draw_bounds_to_sheet() -> None:
    p = _make_plugin({"x0": 10.0, "y0": 5.0, "x1": 110.0, "y1": -95.0})
    out = p.process([{"draw_points": [{"x_mm": 0.0, "y_mm": 0.0}]}])[0]
    # bounds = [min_x, min_y, max_x, max_y]
    assert out["draw_bounds"] == [10.0, -95.0, 110.0, 5.0]
    assert p._reg.points_last == 1


def test_passthrough_when_no_points() -> None:
    p = _make_plugin()
    item = {"frame": "F"}
    assert p.process([item])[0] == item  # без draw_points — без изменений


def test_skips_malformed_points() -> None:
    p = _make_plugin({"src_width": 100, "src_height": 100, "x0": 0, "y0": 0, "x1": 100, "y1": 100})
    pts = [{"x_mm": 50.0, "y_mm": 50.0}, "junk", {"no_coords": 1}]
    out = p.process([{"draw_points": pts}])[0]["draw_points"]
    assert len(out) == 1
    assert out[0]["x_mm"] == 50.0 and out[0]["pen"] == 1  # дефолт pen
