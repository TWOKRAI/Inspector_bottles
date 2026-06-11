# -*- coding: utf-8 -*-
"""Тесты RobotWidgetController — проводка и UX-ограничения (pytest-qt)."""

from __future__ import annotations

from unittest.mock import MagicMock

from multiprocess_prototype.frontend.widgets.tabs.services.robot.controller import (
    RobotWidgetController,
)
from multiprocess_prototype.frontend.widgets.tabs.services.robot.widget import (
    RobotControlWidget,
)


def make_presenter(is_live: bool = True) -> MagicMock:
    presenter = MagicMock()
    presenter.is_live = is_live
    # request/response: по умолчанию ничего не доставляют (колбэк не зовётся)
    presenter.get_telemetry = MagicMock()
    presenter.get_vfd_status = MagicMock()
    presenter.get_draw_progress = MagicMock()
    return presenter


def make_controller(qtbot, is_live: bool = True) -> tuple[RobotControlWidget, RobotWidgetController, MagicMock]:
    widget = RobotControlWidget()
    qtbot.addWidget(widget)
    presenter = make_presenter(is_live)
    controller = RobotWidgetController(widget, presenter)
    return widget, controller, presenter


def test_offline_disables_mode_and_vfd(qtbot) -> None:
    widget, _controller, _presenter = make_controller(qtbot, is_live=False)
    assert not widget._combo_mode.isEnabled()
    assert not widget._btn_vfd_run.isEnabled()
    assert "robot_io" in widget._lbl_status.text()


def test_telemetry_enables_mode_when_free(qtbot) -> None:
    widget, controller, _presenter = make_controller(qtbot)
    controller._on_telemetry({"telemetry": {"x_mm": 1.0, "servo": True}, "free": True, "encoder": 5, "queue_len": 0})
    assert widget._combo_mode.isEnabled()
    assert "X=1.0" in widget._lbl_telemetry.text()


def test_telemetry_busy_locks_mode_switch(qtbot) -> None:
    """Lua применяет режим только в idle — при занятом роботе переключатель заблокирован."""
    widget, controller, _presenter = make_controller(qtbot)
    controller._on_telemetry({"telemetry": {"x_mm": 0.0}, "free": False, "encoder": 0, "queue_len": 1})
    assert not widget._combo_mode.isEnabled()


def test_draw_mode_disables_vfd_buttons(qtbot) -> None:
    """Lua не обслуживает VFD_FLAG в DRAW — кнопки ПЧ дизейблятся с подсказкой."""
    widget, controller, presenter = make_controller(qtbot)
    controller._on_mode("draw")
    assert not widget._btn_vfd_stop.isEnabled()
    assert "DRAW" in widget._lbl_vfd_hint.text()
    controller._on_mode("cvt")
    assert widget._btn_vfd_stop.isEnabled()


def test_vfd_status_shows_delta_comm_errors(qtbot) -> None:
    """comm_errors показывается с дельтой за период (динамика, не абсолют)."""
    widget, controller, _presenter = make_controller(qtbot)
    base = {"running": True, "out_freq_hz": 50.0, "current_a": 15.0, "dcbus_v": 540.0, "heartbeat": 1, "fault": 0}
    controller._on_vfd_status({"vfd": {**base, "comm_errors": 10}, "bridge_alive": True})
    controller._on_vfd_status({"vfd": {**base, "comm_errors": 13}, "bridge_alive": True})
    assert "rsErr=13 (+3)" in widget._lbl_vfd.text()


def test_widget_signals_drive_presenter(qtbot) -> None:
    widget, _controller, presenter = make_controller(qtbot)
    widget._spin_x.setValue(12.5)
    widget._spin_y.setValue(-7.0)
    widget._btn_send_job.click()
    presenter.send_test_job.assert_called_once_with(12.5, -7.0)
    widget._btn_stop3.click()
    presenter.abort.assert_called_with(3)
    widget._btn_vfd_stop.click()
    presenter.vfd_stop.assert_called_once()
    widget._btn_draw_abort.click()
    presenter.abort_draw.assert_called_once()
