# -*- coding: utf-8 -*-
"""Тесты RobotWidgetController — проводка и UX-ограничения (pytest-qt).

Фаза 4 device-hub: все команды с device_id, ПЧ-группа убрана.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from multiprocess_prototype.frontend.widgets.tabs.services.robot.controller import (
    RobotWidgetController,
)
from multiprocess_prototype.frontend.widgets.tabs.services.robot.widget import (
    RobotControlWidget,
)


def make_presenter() -> MagicMock:
    presenter = MagicMock()
    presenter.send_test_job = MagicMock()
    presenter.abort = MagicMock()
    presenter.set_mode = MagicMock()
    presenter.set_servo = MagicMock()
    presenter.set_manual_mode = MagicMock()
    presenter.draw_circle = MagicMock()
    presenter.draw_square = MagicMock()
    presenter.abort_draw = MagicMock()
    presenter.set_pen = MagicMock()
    presenter.set_draw_speed = MagicMock()
    presenter.set_overlap = MagicMock()
    presenter.get_telemetry = MagicMock()
    presenter.get_draw_progress = MagicMock()
    return presenter


def make_controller(qtbot) -> tuple[RobotControlWidget, RobotWidgetController, MagicMock]:
    widget = RobotControlWidget()
    qtbot.addWidget(widget)
    presenter = make_presenter()
    controller = RobotWidgetController(widget, presenter)
    return widget, controller, presenter


def test_no_device_shows_hint(qtbot) -> None:
    """Без выбранного устройства — подсказка."""
    widget, controller, _presenter = make_controller(qtbot)
    controller.set_device(None)
    assert "не выбрано" in widget._lbl_status.text()
    assert not widget._combo_mode.isEnabled()


def test_set_device_updates_status(qtbot) -> None:
    widget, controller, _presenter = make_controller(qtbot)
    controller.set_device("robot_main")
    assert "robot_main" in widget._lbl_status.text()


def test_telemetry_enables_mode_when_free(qtbot) -> None:
    widget, controller, _presenter = make_controller(qtbot)
    controller._device_id = "robot_main"
    controller._apply_telemetry(
        {
            "telemetry": {"x_mm": 1.0, "servo": True},
            "free": True,
            "encoder": 5,
            "queue_len": 0,
        }
    )
    assert widget._combo_mode.isEnabled()
    assert "X=1.0" in widget._lbl_telemetry.text()


def test_telemetry_busy_locks_mode_switch(qtbot) -> None:
    """Lua применяет режим только в idle — при занятом роботе переключатель заблокирован."""
    widget, controller, _presenter = make_controller(qtbot)
    controller._device_id = "robot_main"
    controller._apply_telemetry(
        {
            "telemetry": {"x_mm": 0.0},
            "free": False,
            "encoder": 0,
            "queue_len": 1,
        }
    )
    assert not widget._combo_mode.isEnabled()


def test_send_job_passes_device_id(qtbot) -> None:
    widget, controller, presenter = make_controller(qtbot)
    controller.set_device("robot_main")
    widget._spin_x.setValue(12.5)
    widget._spin_y.setValue(-7.0)
    widget._btn_send_job.click()
    presenter.send_test_job.assert_called_once_with("robot_main", 12.5, -7.0)


def test_stop_passes_device_id(qtbot) -> None:
    widget, controller, presenter = make_controller(qtbot)
    controller.set_device("robot_main")
    widget._btn_stop3.click()
    presenter.abort.assert_called_with("robot_main", 3)


def test_draw_abort_passes_device_id(qtbot) -> None:
    widget, controller, presenter = make_controller(qtbot)
    controller.set_device("robot_main")
    widget._btn_draw_abort.click()
    presenter.abort_draw.assert_called_once_with("robot_main")


def test_no_vfd_group(qtbot) -> None:
    """Виджет робота не содержит ПЧ-группу (Фаза 4: отдельная вкладка)."""
    widget = RobotControlWidget()
    qtbot.addWidget(widget)
    # Нет атрибутов ПЧ
    assert not hasattr(widget, "_btn_vfd_run")
    assert not hasattr(widget, "_lbl_vfd")
    assert not hasattr(widget, "vfd_run_requested")


def test_refresh_calls_telemetry_and_draw(qtbot) -> None:
    """Кнопка Обновить вызывает get_telemetry и get_draw_progress."""
    widget, controller, presenter = make_controller(qtbot)
    controller.set_device("robot_main")
    widget._btn_refresh.click()
    presenter.get_telemetry.assert_called_once()
    presenter.get_draw_progress.assert_called_once()
    # Проверить device_id в первом аргументе
    assert presenter.get_telemetry.call_args[0][0] == "robot_main"


def test_jog_forwards_to_presenter(qtbot) -> None:
    """«Ехать» (jog) → presenter.jog(device_id, dx, dy, spd, absolute)."""
    widget, controller, presenter = make_controller(qtbot)
    controller.set_device("robot_main")
    widget.jog_requested.emit(15.0, -20.0, 30, False)
    presenter.jog.assert_called_once_with("robot_main", 15.0, -20.0, 30, False)


def test_jog_abort_forwards_to_presenter(qtbot) -> None:
    """«Стоп» jog → presenter.jog_abort(device_id)."""
    widget, controller, presenter = make_controller(qtbot)
    controller.set_device("robot_main")
    widget.jog_abort_requested.emit()
    presenter.jog_abort.assert_called_once_with("robot_main")


def test_jog_button_click_emits(qtbot) -> None:
    """Клик по «Ехать» с полей виджета доходит до presenter."""
    widget, controller, presenter = make_controller(qtbot)
    controller.set_device("robot_main")
    widget._jog_dx.setValue(10.0)
    widget._jog_dy.setValue(5.0)
    widget._jog_spd.setValue(25)
    widget._btn_jog.click()
    presenter.jog.assert_called_once_with("robot_main", 10.0, 5.0, 25, False)
