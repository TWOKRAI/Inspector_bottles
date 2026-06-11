# -*- coding: utf-8 -*-
"""Тесты RobotPresenter — мост/sender/runner как моки, без Qt."""

from __future__ import annotations

from unittest.mock import MagicMock

from multiprocess_prototype.frontend.widgets.tabs.services.robot.presenter import (
    RobotPresenter,
    _unwrap,
)


class FakeTopology:
    """Топология с нодой робота (robot_io + vfd_control + robot_draw co-located)."""

    def __init__(self, with_robot: bool = True) -> None:
        plugins = (
            [{"plugin_name": "robot_io"}, {"plugin_name": "vfd_control"}, {"plugin_name": "robot_draw"}]
            if with_robot
            else []
        )
        self._topo = {"processes": [{"process_name": "robot", "plugins": plugins}]}

    def load(self):
        topo = self._topo

        class _Doc:
            def to_dict(self) -> dict:
                return topo

        return _Doc()


class ImmediateRunner:
    """RequestRunner-стаб: исполняет синхронно (тестам не нужен поток)."""

    def submit(self, fn, on_result) -> None:
        on_result(fn())


def make_presenter(*, with_robot: bool = True, bridge_ok: bool = True):
    bridge = MagicMock()
    bridge.on_action_command.return_value = bridge_ok
    sender = MagicMock()
    presenter = RobotPresenter(
        bridge=bridge,
        topology=FakeTopology(with_robot),
        command_sender=sender,
        request_runner=ImmediateRunner(),
    )
    return presenter, bridge, sender


# --- топология / is_live ---


def test_finds_robot_process() -> None:
    presenter, _b, _s = make_presenter()
    assert presenter.robot_process_name() == "robot"
    assert presenter.is_live


def test_no_robot_node() -> None:
    presenter, _b, _s = make_presenter(with_robot=False)
    assert presenter.robot_process_name() is None
    assert not presenter.is_live


def test_degraded_without_bridge() -> None:
    presenter = RobotPresenter(bridge=None, topology=FakeTopology())
    assert not presenter.is_live
    assert presenter.send_test_job(1, 2) is False  # graceful, не падает


# --- адресация команд: плагин + имя + аргументы ---


def test_robot_commands_routed_to_robot_io() -> None:
    presenter, bridge, _s = make_presenter()
    presenter.send_test_job(10.5, -2.0)
    bridge.on_action_command.assert_called_with("robot_io", "send_test_job", {"x": 10.5, "y": -2.0})
    presenter.abort(3)
    bridge.on_action_command.assert_called_with("robot_io", "abort", {"mode": 3})
    presenter.set_mode("draw")
    bridge.on_action_command.assert_called_with("robot_io", "set_mode", {"mode": "draw"})
    presenter.set_manual_mode(True)
    bridge.on_action_command.assert_called_with("robot_io", "set_manual_mode", {"on": True})


def test_vfd_commands_routed_to_vfd_control() -> None:
    presenter, bridge, _s = make_presenter()
    presenter.vfd_run(50.0, reverse=True)
    bridge.on_action_command.assert_called_with("vfd_control", "vfd_run", {"freq": 50.0, "reverse": True})
    presenter.vfd_stop()
    bridge.on_action_command.assert_called_with("vfd_control", "vfd_stop", {})


def test_draw_commands_routed_to_robot_draw() -> None:
    presenter, bridge, _s = make_presenter()
    presenter.draw_circle(1, 2, 3, -0.5)
    bridge.on_action_command.assert_called_with(
        "robot_draw", "draw_circle", {"cx": 1.0, "cy": 2.0, "r": 3.0, "z": -0.5}
    )
    presenter.abort_draw()
    bridge.on_action_command.assert_called_with("robot_draw", "abort_draw", {})


# --- request/response ---


def test_get_telemetry_round_trip() -> None:
    presenter, _b, sender = make_presenter()
    sender.request_command.return_value = {"status": "ok", "telemetry": {"x_mm": 1.0}, "free": True}
    results: list[dict] = []
    presenter.get_telemetry(results.append)
    sender.request_command.assert_called_once_with("robot", "get_telemetry", {})
    assert results == [{"status": "ok", "telemetry": {"x_mm": 1.0}, "free": True}]


def test_request_without_process_returns_empty() -> None:
    presenter, _b, sender = make_presenter(with_robot=False)
    results: list[dict] = []
    presenter.get_vfd_status(results.append)
    sender.request_command.assert_not_called()
    assert results == [{}]


# --- _unwrap ---


def test_unwrap_plain_and_wrapped() -> None:
    assert _unwrap({"status": "ok", "free": True}) == {"status": "ok", "free": True}
    assert _unwrap({"result": {"status": "ok", "free": True}}) == {"status": "ok", "free": True}
    assert _unwrap("garbage") == {}
