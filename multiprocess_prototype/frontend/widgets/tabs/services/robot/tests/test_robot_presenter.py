# -*- coding: utf-8 -*-
"""Тесты RobotPresenter — команды → процесс devices, без Qt.

Фаза 4 device-hub: все команды идут в target ``devices`` с device_id.
Резолв топологии убран.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from multiprocess_prototype.frontend.widgets.tabs.services.robot.presenter import (
    RobotPresenter,
    _unwrap,
)


class ImmediateRunner:
    """RequestRunner-стаб: исполняет синхронно (тестам не нужен поток)."""

    def submit(self, fn, on_result=None) -> None:
        result = fn()
        if on_result:
            on_result(result)


def make_presenter():
    sender = MagicMock()
    runner = ImmediateRunner()
    presenter = RobotPresenter(command_sender=sender, request_runner=runner)
    return presenter, sender


# --- адресация команд: все → devices с device_id ---


def test_send_test_job_routed_to_devices() -> None:
    presenter, sender = make_presenter()
    sender.request_command.return_value = {"status": "ok"}
    presenter.send_test_job("robot_main", 10.5, -2.0)
    sender.request_command.assert_called_with(
        "devices", "robot_send_test_job", {"device_id": "robot_main", "x": 10.5, "y": -2.0}
    )


def test_abort_routed_to_devices() -> None:
    presenter, sender = make_presenter()
    sender.request_command.return_value = {"status": "ok"}
    presenter.abort("robot_main", 3)
    sender.request_command.assert_called_with("devices", "robot_abort", {"device_id": "robot_main", "mode": 3})


def test_set_mode_routed_to_devices() -> None:
    presenter, sender = make_presenter()
    sender.request_command.return_value = {"status": "ok"}
    presenter.set_mode("robot_main", "draw")
    sender.request_command.assert_called_with("devices", "robot_set_mode", {"device_id": "robot_main", "mode": "draw"})


def test_set_manual_mode() -> None:
    presenter, sender = make_presenter()
    sender.request_command.return_value = {"status": "ok"}
    presenter.set_manual_mode("robot_main", True)
    sender.request_command.assert_called_with(
        "devices", "robot_set_manual_mode", {"device_id": "robot_main", "on": True}
    )


def test_draw_circle_routed_to_devices() -> None:
    presenter, sender = make_presenter()
    sender.request_command.return_value = {"status": "ok"}
    presenter.draw_circle("robot_main", 1, 2, 3, -0.5)
    sender.request_command.assert_called_with(
        "devices",
        "robot_draw_circle",
        {"device_id": "robot_main", "cx": 1.0, "cy": 2.0, "r": 3.0, "z": -0.5},
    )


def test_abort_draw() -> None:
    presenter, sender = make_presenter()
    sender.request_command.return_value = {"status": "ok"}
    presenter.abort_draw("robot_main")
    sender.request_command.assert_called_with(
        "devices",
        "robot_draw_abort",
        {"device_id": "robot_main"},
    )


# --- webcam_sketch: команды процессам pipeline (camera_0/points), НЕ в devices ---


def test_freeze_camera_routed_to_camera_process() -> None:
    presenter, sender = make_presenter()
    sender.request_command.return_value = {"status": "ok", "frozen": True}
    results: list[dict] = []
    presenter.freeze_camera("camera_0", results.append)
    sender.request_command.assert_called_once_with("camera_0", "freeze_capture", {})
    assert results == [{"status": "ok", "frozen": True}]


def test_resume_camera_routed() -> None:
    presenter, sender = make_presenter()
    sender.request_command.return_value = {"status": "ok"}
    presenter.resume_camera("camera_0")
    sender.request_command.assert_called_with("camera_0", "unfreeze_capture", {})


def test_send_to_robot_routed_to_points_process() -> None:
    presenter, sender = make_presenter()
    sender.request_command.return_value = {"status": "ok", "armed": True}
    presenter.send_to_robot("points")
    sender.request_command.assert_called_with("points", "robot_draw_send", {})


def test_pipeline_command_without_sender() -> None:
    presenter = RobotPresenter(command_sender=None, request_runner=None)
    results: list[dict] = []
    presenter.send_to_robot("points", results.append)
    assert results == [{}]


# --- request/response ---


def test_get_telemetry_round_trip() -> None:
    presenter, sender = make_presenter()
    sender.request_command.return_value = {
        "status": "ok",
        "telemetry": {"x_mm": 1.0},
        "free": True,
    }
    results: list[dict] = []
    presenter.get_telemetry("robot_main", results.append)
    sender.request_command.assert_called_once_with(
        "devices",
        "robot_get_telemetry",
        {"device_id": "robot_main"},
    )
    assert results == [{"status": "ok", "telemetry": {"x_mm": 1.0}, "free": True}]


def test_request_without_sender_returns_empty() -> None:
    presenter = RobotPresenter(command_sender=None, request_runner=None)
    results: list[dict] = []
    presenter.get_telemetry("robot_main", results.append)
    assert results == [{}]


# --- _unwrap ---


def test_unwrap_plain_and_wrapped() -> None:
    assert _unwrap({"status": "ok", "free": True}) == {"status": "ok", "free": True}
    assert _unwrap({"result": {"status": "ok", "free": True}}) == {"status": "ok", "free": True}
    assert _unwrap("garbage") == {}
