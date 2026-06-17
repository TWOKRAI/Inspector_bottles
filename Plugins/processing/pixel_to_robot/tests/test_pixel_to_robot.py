"""Тесты PixelToRobotPlugin — применение гомографии px→мм робота к центру диска."""

from __future__ import annotations

import yaml

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

from Plugins.processing.pixel_to_robot.plugin import PixelToRobotPlugin

# Гомография-аффинаж: x_mm = 0.5·px_x + 10, y_mm = 0.5·px_y − 20 (w=1).
_H = [[0.5, 0.0, 10.0], [0.0, 0.5, -20.0], [0.0, 0.0, 1.0]]


def _write_calib(dirpath, camera_id: str = "cam0", h=_H) -> None:
    (dirpath / f"{camera_id}.yaml").write_text(
        yaml.safe_dump({"px_to_mm": h, "camera_id": camera_id}, allow_unicode=True),
        encoding="utf-8",
    )


def _make_plugin(config: dict) -> PixelToRobotPlugin:
    services = MockProcessServices(name="calib", config=config)
    ctx = PluginContext(services=services, config=config)
    plugin = PixelToRobotPlugin()
    plugin.configure(ctx)
    return plugin


def test_registered() -> None:
    from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry
    import Plugins.processing.pixel_to_robot.plugin  # noqa: F401

    entry = PluginRegistry.get("pixel_to_robot")
    assert entry is not None
    assert entry.category == "processing"


def test_applies_homography_from_sidecar(tmp_path) -> None:
    _write_calib(tmp_path)
    p = _make_plugin({"camera_id": "cam0", "calibration_dir": str(tmp_path)})
    assert p._reg.loaded is True
    out = p.process([{"sidecar": {"center_px": [100, 40]}}])[0]
    assert out["pick_xy"] == {"x_mm": 60.0, "y_mm": 0.0}  # 0.5·100+10, 0.5·40−20
    assert p._reg.conversions == 1


def test_applies_homography_from_top_level(tmp_path) -> None:
    _write_calib(tmp_path)
    p = _make_plugin({"camera_id": "cam0", "calibration_dir": str(tmp_path)})
    out = p.process([{"center_px": [0, 0]}])[0]
    assert out["pick_xy"] == {"x_mm": 10.0, "y_mm": -20.0}


def test_roi_offset_applied_before_homography(tmp_path) -> None:
    _write_calib(tmp_path)
    p = _make_plugin({"camera_id": "cam0", "calibration_dir": str(tmp_path), "roi_offset_x": 20, "roi_offset_y": 60})
    # px (80,−20) + offset (20,60) = (100,40) → (60, 0)
    out = p.process([{"sidecar": {"center_px": [80, -20]}}])[0]
    assert out["pick_xy"] == {"x_mm": 60.0, "y_mm": 0.0}


def test_passthrough_when_no_calibration(tmp_path) -> None:
    # Файла нет → loaded=False → pick_xy не добавляется, item не меняется.
    p = _make_plugin({"camera_id": "missing", "calibration_dir": str(tmp_path)})
    assert p._reg.loaded is False
    item = {"sidecar": {"center_px": [100, 40]}, "frame": "F"}
    assert p.process([item])[0] == item


def test_passthrough_when_no_center(tmp_path) -> None:
    _write_calib(tmp_path)
    p = _make_plugin({"camera_id": "cam0", "calibration_dir": str(tmp_path)})
    item = {"predictions": [{"label": "А"}]}  # без center_px
    out = p.process([item])[0]
    assert "pick_xy" not in out
    assert out == item


def test_reload_after_wizard(tmp_path) -> None:
    # Старт без калибровки → пусто; файл появился → reload → переводит.
    p = _make_plugin({"camera_id": "cam0", "calibration_dir": str(tmp_path)})
    assert p._reg.loaded is False
    _write_calib(tmp_path)
    res = p.cmd_reload({})
    assert res["loaded"] is True
    out = p.process([{"sidecar": {"center_px": [0, 0]}}])[0]
    assert out["pick_xy"] == {"x_mm": 10.0, "y_mm": -20.0}


# ======================================================================
# Линейный режим (билинейная интерполяция, без файла калибровки)
# ======================================================================


def test_bilinear_corners() -> None:
    """Чистая geometry: угловые точки px(0,0)→TL, px(W,0)→TR, px(W,H)→BR, px(0,H)→BL."""
    from Plugins.processing.pixel_to_robot.geometry import bilinear_px_to_mm

    tl = (100.0, -200.0)
    tr = (300.0, -200.0)
    br = (300.0, 0.0)
    bl = (100.0, 0.0)

    # px(0,0) → TL
    assert bilinear_px_to_mm(0, 0, 800, 481, tl, tr, br, bl) == tl
    # px(W,0) → TR
    assert bilinear_px_to_mm(800, 0, 800, 481, tl, tr, br, bl) == tr
    # px(W,H) → BR
    assert bilinear_px_to_mm(800, 481, 800, 481, tl, tr, br, bl) == br
    # px(0,H) → BL
    assert bilinear_px_to_mm(0, 481, 800, 481, tl, tr, br, bl) == bl


def test_bilinear_center() -> None:
    """Центр ROI (W/2, H/2) → среднее 4 углов (для прямоугольника)."""
    from Plugins.processing.pixel_to_robot.geometry import bilinear_px_to_mm

    tl = (100.0, -200.0)
    tr = (300.0, -200.0)
    br = (300.0, 0.0)
    bl = (100.0, 0.0)

    x, y = bilinear_px_to_mm(400, 240.5, 800, 481, tl, tr, br, bl)
    expected_x = (tl[0] + tr[0] + br[0] + bl[0]) / 4
    expected_y = (tl[1] + tr[1] + br[1] + bl[1]) / 4
    assert abs(x - expected_x) < 1e-9
    assert abs(y - expected_y) < 1e-9


def test_bilinear_guard_zero_size() -> None:
    """src_w/src_h <= 0 не должно давать деление на ноль (guard max(1,...))."""
    from Plugins.processing.pixel_to_robot.geometry import bilinear_px_to_mm

    tl = (0.0, 0.0)
    tr = (10.0, 0.0)
    br = (10.0, 10.0)
    bl = (0.0, 10.0)
    # Не бросает ZeroDivisionError
    result = bilinear_px_to_mm(0, 0, 0, 0, tl, tr, br, bl)
    assert isinstance(result, tuple) and len(result) == 2


def test_linear_mode_produces_pick_xy_without_file(tmp_path) -> None:
    """use_linear=True → pick_xy выдаётся БЕЗ файла калибровки."""
    p = _make_plugin(
        {
            "camera_id": "nonexistent",
            "calibration_dir": str(tmp_path),
            "use_linear": True,
            "lin_src_width": 800,
            "lin_src_height": 481,
            "lin_tl_x": 100.0,
            "lin_tl_y": -200.0,
            "lin_tr_x": 300.0,
            "lin_tr_y": -200.0,
            "lin_br_x": 300.0,
            "lin_br_y": 0.0,
            "lin_bl_x": 100.0,
            "lin_bl_y": 0.0,
        }
    )
    assert p._reg.loaded is True  # линейный режим «загружен» всегда
    assert p._reg.use_linear is True

    # px(0,0) → TL
    out = p.process([{"sidecar": {"center_px": [0, 0]}}])[0]
    assert "pick_xy" in out
    assert out["pick_xy"]["x_mm"] == 100.0
    assert out["pick_xy"]["y_mm"] == -200.0
    assert p._reg.conversions == 1


def test_linear_mode_passthrough_no_center(tmp_path) -> None:
    """use_linear=True, но item без center_px → passthrough, без ошибки."""
    p = _make_plugin(
        {
            "camera_id": "nonexistent",
            "calibration_dir": str(tmp_path),
            "use_linear": True,
        }
    )
    item = {"predictions": [{"label": "А"}]}
    out = p.process([item])[0]
    assert "pick_xy" not in out
    assert out == item


def test_linear_mode_reload_keeps_working(tmp_path) -> None:
    """cmd_reload в линейном режиме не ломает — loaded остаётся True."""
    p = _make_plugin(
        {
            "camera_id": "nonexistent",
            "calibration_dir": str(tmp_path),
            "use_linear": True,
        }
    )
    assert p._reg.loaded is True
    res = p.cmd_reload({})
    assert res["loaded"] is True
