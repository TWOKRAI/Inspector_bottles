# -*- coding: utf-8 -*-
"""Тесты VfdWidgetController — проводка и UX-ограничения (pytest-qt)."""

from __future__ import annotations

from unittest.mock import MagicMock

from multiprocess_prototype.frontend.widgets.tabs.services.vfd.controller import (
    VfdWidgetController,
)
from multiprocess_prototype.frontend.widgets.tabs.services.vfd.widget import (
    VfdControlWidget,
)


def make_presenter() -> MagicMock:
    presenter = MagicMock()
    presenter.vfd_run = MagicMock()
    presenter.vfd_stop = MagicMock()
    presenter.vfd_set_freq = MagicMock()
    presenter.vfd_reset_fault = MagicMock()
    presenter.vfd_get_status = MagicMock()
    presenter.device_describe = MagicMock()
    return presenter


def make_controller(qtbot) -> tuple[VfdControlWidget, VfdWidgetController, MagicMock]:
    widget = VfdControlWidget()
    qtbot.addWidget(widget)
    presenter = make_presenter()
    controller = VfdWidgetController(widget, presenter)
    return widget, controller, presenter


def test_run_button_calls_presenter(qtbot) -> None:
    widget, controller, presenter = make_controller(qtbot)
    controller.set_device("vfd_belt")
    widget._spin_freq.setValue(25.0)
    widget._btn_run.click()
    presenter.vfd_run.assert_called_once_with("vfd_belt", 25.0, False)


def test_run_reverse_button(qtbot) -> None:
    widget, controller, presenter = make_controller(qtbot)
    controller.set_device("vfd_belt")
    widget._spin_freq.setValue(15.0)
    widget._btn_run_rev.click()
    presenter.vfd_run.assert_called_once_with("vfd_belt", 15.0, True)


def test_stop_button(qtbot) -> None:
    widget, controller, presenter = make_controller(qtbot)
    controller.set_device("vfd_belt")
    widget._btn_stop.click()
    presenter.vfd_stop.assert_called_once_with("vfd_belt")


def test_set_freq_button(qtbot) -> None:
    widget, controller, presenter = make_controller(qtbot)
    controller.set_device("vfd_belt")
    widget._spin_freq.setValue(33.3)
    widget._btn_set_freq.click()
    presenter.vfd_set_freq.assert_called_once_with("vfd_belt", 33.3)


def test_reset_fault_button(qtbot) -> None:
    widget, controller, presenter = make_controller(qtbot)
    controller.set_device("vfd_belt")
    widget._btn_reset.click()
    presenter.vfd_reset_fault.assert_called_once_with("vfd_belt")


def test_no_device_disables_controls(qtbot) -> None:
    widget, controller, _presenter = make_controller(qtbot)
    controller.set_device(None)
    assert not widget._btn_run.isEnabled()
    assert "не выбрано" in widget._lbl_status.text()


def test_set_device_requests_describe(qtbot) -> None:
    """set_device() вызывает device_describe для лимитов и gating."""
    widget, controller, presenter = make_controller(qtbot)
    controller.set_device("vfd_belt")
    presenter.device_describe.assert_called_once_with("vfd_belt", controller._on_describe)


def test_describe_sets_freq_range(qtbot) -> None:
    """describe с protocol_meta.cmd_freq устанавливает лимиты spinbox."""
    widget, controller, _presenter = make_controller(qtbot)
    controller._on_describe(
        {
            "protocol_meta": {"cmd_freq": {"min": 5, "max": 60}},
        }
    )
    assert widget._spin_freq.minimum() == 5.0
    assert widget._spin_freq.maximum() == 60.0


def test_describe_draw_gating(qtbot) -> None:
    """describe с carrier.mode=draw дизейблит кнопки."""
    widget, controller, _presenter = make_controller(qtbot)
    controller._device_id = "vfd_belt"
    controller._on_describe(
        {
            "carrier": {"mode": "draw"},
        }
    )
    assert not widget._btn_run.isEnabled()
    assert "DRAW" in widget._lbl_hint.text()


def test_status_push_shows_values(qtbot) -> None:
    """Push-статус через _on_status_push обновляет виджет."""
    widget, controller, _presenter = make_controller(qtbot)
    controller._device_id = "vfd_belt"
    controller._on_status_push(
        "devices.state.vfd_belt.status",
        {
            "running": True,
            "out_freq_hz": 50.0,
            "current_a": 15.0,
            "dcbus_v": 540.0,
            "heartbeat": 42,
            "comm_errors": 5,
            "fault": 0,
            "quality": "good",
        },
    )
    assert "RUN" in widget._lbl_status.text()
    assert "50.00" in widget._lbl_status.text()
    assert "актуальны" in widget._lbl_quality.text()


def test_comm_errors_delta(qtbot) -> None:
    """comm_errors показывается с дельтой за период."""
    widget, controller, _presenter = make_controller(qtbot)
    controller._device_id = "vfd_belt"
    base = {
        "running": False,
        "out_freq_hz": 0,
        "current_a": 0,
        "dcbus_v": 0,
        "heartbeat": 1,
        "fault": 0,
    }
    controller._apply_vfd_status({**base, "comm_errors": 10})
    controller._apply_vfd_status({**base, "comm_errors": 17})
    assert "rsErr=17 (+7)" in widget._lbl_status.text()


def test_quality_stale(qtbot) -> None:
    """quality=stale показывает предупреждение."""
    widget, controller, _presenter = make_controller(qtbot)
    controller._apply_vfd_status(
        {
            "running": False,
            "out_freq_hz": 0,
            "current_a": 0,
            "dcbus_v": 0,
            "heartbeat": 0,
            "comm_errors": 0,
            "fault": 0,
            "quality": "stale",
            "reason": "carrier busy",
        }
    )
    assert "устарели" in widget._lbl_quality.text()


def test_refresh_button_calls_get_status(qtbot) -> None:
    """Кнопка Обновить вызывает vfd_get_status."""
    widget, controller, presenter = make_controller(qtbot)
    controller._device_id = "vfd_belt"
    widget._btn_refresh.click()
    presenter.vfd_get_status.assert_called_once()
