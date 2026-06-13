# -*- coding: utf-8 -*-
"""Тесты CalibrationController + resolve_calibration_process (pytest-qt)."""

from __future__ import annotations

from unittest.mock import MagicMock

from multiprocess_prototype.frontend.widgets.tabs.services.robot.calibration.controller import (
    CalibrationController,
    build_calibration_controls,
    resolve_calibration_process,
)
from multiprocess_prototype.frontend.widgets.tabs.services.robot.calibration.widget import (
    CalibrationWizardWidget,
)


class FakeBindings:
    def __init__(self):
        self.fanouts = []

    def bind_fanout(self, path, cb, owner=None):
        self.fanouts.append((path, cb, owner))


class FakeRecipes:
    def __init__(self, active, raw):
        self._active = active
        self._raw = raw

    def get_active(self):
        return self._active

    def read_raw(self, _slug):
        return self._raw


# --- resolve_calibration_process -------------------------------------------
def test_resolve_finds_process():
    raw = {
        "blueprint": {
            "processes": [
                {"process_name": "detector", "plugins": [{"plugin_name": "hsv_mask"}]},
                {"process_name": "cal_node", "plugins": [{"plugin_name": "camera_robot_calibration"}]},
            ]
        }
    }
    assert resolve_calibration_process(FakeRecipes("r1", raw)) == "cal_node"


def test_resolve_fallback_no_match():
    raw = {"blueprint": {"processes": [{"process_name": "x", "plugins": [{"plugin_name": "hsv_mask"}]}]}}
    assert resolve_calibration_process(FakeRecipes("r1", raw)) == "cal"


def test_resolve_fallback_none_recipes():
    assert resolve_calibration_process(None) == "cal"


# --- CalibrationController (Qt) ---------------------------------------------
def _build(qtbot):
    widget = CalibrationWizardWidget()
    qtbot.addWidget(widget)
    presenter = MagicMock()
    bindings = FakeBindings()
    controller = CalibrationController(widget, presenter, bindings=bindings)
    return widget, presenter, bindings, controller


def test_set_device_binds_progress(qtbot):
    widget, presenter, bindings, controller = _build(qtbot)
    controller.set_device("robot_main")
    assert any(p == "calibration.state.cam0.progress" for p, _cb, _o in bindings.fanouts)


def test_begin_includes_robot_id(qtbot):
    widget, presenter, bindings, controller = _build(qtbot)
    controller.set_device("robot_main")
    widget.begin_requested.emit("cam7", "vfd_belt")
    presenter.begin.assert_called_once_with("cam7", "robot_main", "vfd_belt")


def test_set_point_routes_index(qtbot):
    widget, presenter, bindings, controller = _build(qtbot)
    controller.set_device("robot_main")
    widget.set_point_requested.emit(3)
    presenter.set_robot_point.assert_called_once_with(3)


def test_progress_push_updates_widget(qtbot):
    widget, presenter, bindings, controller = _build(qtbot)
    controller.set_device("robot_main")
    snap = {
        "phase": "saved",
        "message": "Готово",
        "error": None,
        "captured": True,
        "live_found": 5,
        "expected_points": 5,
        "points_collected": 5,
        "scale_done": True,
        "mm_per_count": 0.05,
        "belt_dir": [1.0, 0.0],
        "reproj": {"center": 0.4, "mean": 0.3, "max": 0.5},
        "passed": True,
        "saved_path": "config/calibration/cam0.yaml",
        "reproj_threshold_mm": 2.0,
    }
    controller._on_progress_push("calibration.state.cam0.progress", snap)
    assert widget._btn_save.isEnabled()  # passed → save активна
    assert "0.4" in widget._lbl_reproj.text()
    assert "cam0.yaml" in widget._lbl_saved.text()


def test_build_calibration_controls_wires(qtbot):
    runtime = MagicMock()
    runtime.command_sender = MagicMock()
    widget, controller, presenter = build_calibration_controls(
        runtime=runtime, request_runner=MagicMock(), bindings=FakeBindings(), target_process="cal_node"
    )
    qtbot.addWidget(widget)
    assert presenter._target == "cal_node"
    assert isinstance(controller, CalibrationController)
