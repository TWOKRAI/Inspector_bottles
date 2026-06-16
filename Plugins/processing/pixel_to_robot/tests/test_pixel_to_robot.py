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
