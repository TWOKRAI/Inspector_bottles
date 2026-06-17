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
    # Кадр 640x480 → лист (0,0) ЛВ … (200,-200) ПН. keep_aspect=False → заполнить всю зону.
    p = _make_plugin(
        {"src_width": 640, "src_height": 480, "x0": 0.0, "y0": 0.0, "x1": 200.0, "y1": -200.0, "keep_aspect": False}
    )
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
    # bounds = упорядоченные углы [x0, y0 (ЛВ), x1, y1 (ПН)] — для ориентации превью.
    assert out["draw_bounds"] == [10.0, 5.0, 110.0, -95.0]
    assert p._reg.points_last == 1


def test_draw_scale_shrinks_drawing_inside_sheet() -> None:
    # draw_scale=0.5 + keep_aspect=False — рисунок занимает половину листа (от угла x0,y0).
    p = _make_plugin(
        {
            "src_width": 640,
            "src_height": 480,
            "x0": 0.0,
            "y0": 0.0,
            "x1": 200.0,
            "y1": 200.0,
            "draw_scale": 0.5,
            "keep_aspect": False,
        }
    )
    out = p.process([{"draw_points": [{"x_mm": 640.0, "y_mm": 480.0, "pen": 1}]}])[0]
    # Полный кадр без scale → (200,200); со scale 0.5 → (100,100).
    assert out["draw_points"][0]["x_mm"] == 100.0
    assert out["draw_points"][0]["y_mm"] == 100.0
    # Лист (draw_bounds) не изменился — рисунок внутри него.
    assert out["draw_bounds"] == [0.0, 0.0, 200.0, 200.0]


def test_offset_shifts_drawing_on_sheet() -> None:
    # offset сдвигает рисунок по столу (мм), лист тот же. keep_aspect=False для точного теста.
    p = _make_plugin(
        {
            "src_width": 640,
            "src_height": 480,
            "x0": 0.0,
            "y0": 0.0,
            "x1": 200.0,
            "y1": 200.0,
            "offset_x": 30.0,
            "offset_y": -10.0,
            "keep_aspect": False,
        }
    )
    out = p.process([{"draw_points": [{"x_mm": 0.0, "y_mm": 0.0, "pen": 1}]}])[0]
    assert out["draw_points"][0]["x_mm"] == 30.0
    assert out["draw_points"][0]["y_mm"] == -10.0
    assert out["draw_bounds"] == [0.0, 0.0, 200.0, 200.0]


def test_keep_aspect_centers_without_distortion() -> None:
    # keep_aspect: кадр 640x480 (4:3) в зону 200x200 (квадрат) → единый масштаб + центрирование.
    # su=min(200/640, 200/480)=0.3125. По X заполняет (200), по Y 480*0.3125=150, пад=(200-150)/2=25.
    p = _make_plugin(
        {"src_width": 640, "src_height": 480, "x0": 0.0, "y0": 0.0, "x1": 200.0, "y1": 200.0, "keep_aspect": True}
    )
    out = p.process([{"draw_points": [{"x_mm": 0.0, "y_mm": 0.0}, {"x_mm": 640.0, "y_mm": 480.0}]}])[0]
    a, b = out["draw_points"]
    assert a["x_mm"] == 0.0 and a["y_mm"] == 25.0  # верх-лево: X с края, Y с отступом-центром
    assert b["x_mm"] == 200.0 and b["y_mm"] == 175.0  # низ-право: X до края, Y центрирован
    # Пропорции сохранены: ширина 200, высота 150 (4:3), без искажения.


def test_swap_axes_maps_image_to_rotated_sheet() -> None:
    # Лист повёрнут 90°: image-x → робот-Y, image-y → робот-X. keep_aspect=False для точного теста.
    # ВЛ(325,-223) ВП(325,-17) НЛ(544,-223) НП(544,-17).
    p = _make_plugin(
        {
            "src_width": 640,
            "src_height": 480,
            "x0": 325.0,
            "y0": -223.0,
            "x1": 544.0,
            "y1": -17.0,
            "swap_axes": True,
            "keep_aspect": False,
        }
    )
    pts = [
        {"x_mm": 0.0, "y_mm": 0.0},  # image TL → ВЛ
        {"x_mm": 640.0, "y_mm": 0.0},  # image TR → ВП
        {"x_mm": 0.0, "y_mm": 480.0},  # image BL → НЛ
        {"x_mm": 640.0, "y_mm": 480.0},  # image BR → НП
    ]
    out = p.process([{"draw_points": pts}])[0]["draw_points"]
    assert (out[0]["x_mm"], out[0]["y_mm"]) == (325.0, -223.0)
    assert (out[1]["x_mm"], out[1]["y_mm"]) == (325.0, -17.0)
    assert (out[2]["x_mm"], out[2]["y_mm"]) == (544.0, -223.0)
    assert (out[3]["x_mm"], out[3]["y_mm"]) == (544.0, -17.0)


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


# --- прижим к рабочей зоне (листу) ---


def test_clamp_to_zone_pins_out_of_sheet_to_edge() -> None:
    # offset выталкивает точку за лист → прижата к границе (X на 200, Y на 200).
    p = _make_plugin(
        {
            "src_width": 640,
            "src_height": 480,
            "x0": 0.0,
            "y0": 0.0,
            "x1": 200.0,
            "y1": 200.0,
            "offset_x": 500.0,  # увести далеко за правый край
            "offset_y": 500.0,
            "keep_aspect": False,
            "clamp_to_zone": True,
        }
    )
    out = p.process([{"draw_points": [{"x_mm": 640.0, "y_mm": 480.0, "pen": 1}]}])[0]
    assert out["draw_points"][0]["x_mm"] == 200.0  # прижато к ПН-границе
    assert out["draw_points"][0]["y_mm"] == 200.0
    assert p._reg.points_clamped == 1


def test_clamp_handles_reversed_corners() -> None:
    # Лист с y0>y1 (Y-вверх): зона по Y = [-200, 0]; точка ниже прижимается к -200.
    p = _make_plugin(
        {
            "src_width": 640,
            "src_height": 480,
            "x0": 0.0,
            "y0": 0.0,
            "x1": 200.0,
            "y1": -200.0,
            "offset_y": -500.0,
            "keep_aspect": False,
            "clamp_to_zone": True,
        }
    )
    out = p.process([{"draw_points": [{"x_mm": 0.0, "y_mm": 480.0, "pen": 1}]}])[0]
    assert out["draw_points"][0]["y_mm"] == -200.0  # прижато к нижней (по модулю) границе


def test_clamp_off_allows_out_of_zone() -> None:
    p = _make_plugin(
        {
            "src_width": 640,
            "src_height": 480,
            "x0": 0.0,
            "y0": 0.0,
            "x1": 200.0,
            "y1": 200.0,
            "offset_x": 500.0,
            "keep_aspect": False,
            "clamp_to_zone": False,
        }
    )
    out = p.process([{"draw_points": [{"x_mm": 640.0, "y_mm": 0.0, "pen": 1}]}])[0]
    assert out["draw_points"][0]["x_mm"] == 700.0  # 200 + 500 offset, без прижима
    assert p._reg.points_clamped == 0
