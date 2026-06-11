# -*- coding: utf-8 -*-
"""Тесты VfdPresenter — команды через sender/runner, без Qt."""

from __future__ import annotations

from unittest.mock import MagicMock

from multiprocess_prototype.frontend.widgets.tabs.services.vfd.presenter import (
    VfdPresenter,
)


class ImmediateRunner:
    """RequestRunner-стаб: исполняет синхронно."""

    def submit(self, fn, on_result) -> None:
        on_result(fn())


def make_presenter():
    sender = MagicMock()
    runner = ImmediateRunner()
    presenter = VfdPresenter(command_sender=sender, request_runner=runner)
    return presenter, sender


def test_vfd_run_sends_correct_args() -> None:
    presenter, sender = make_presenter()
    sender.request_command.return_value = {"status": "ok"}
    results: list = []
    presenter.vfd_run("vfd_belt", 25.0, reverse=True, on_result=results.append)
    sender.request_command.assert_called_once_with(
        "devices", "vfd_run", {"device_id": "vfd_belt", "freq_hz": 25.0, "direction": 1}
    )


def test_vfd_stop_sends_device_id() -> None:
    presenter, sender = make_presenter()
    sender.request_command.return_value = {"status": "ok"}
    presenter.vfd_stop("vfd_belt")
    sender.request_command.assert_called_once_with("devices", "vfd_stop", {"device_id": "vfd_belt"})


def test_vfd_set_freq_sends_hz() -> None:
    presenter, sender = make_presenter()
    sender.request_command.return_value = {"status": "ok"}
    presenter.vfd_set_freq("vfd_belt", 30.5)
    sender.request_command.assert_called_once_with(
        "devices", "vfd_set_freq", {"device_id": "vfd_belt", "freq_hz": 30.5}
    )


def test_vfd_reset_fault() -> None:
    presenter, sender = make_presenter()
    sender.request_command.return_value = {"status": "ok"}
    presenter.vfd_reset_fault("vfd_belt")
    sender.request_command.assert_called_once_with("devices", "vfd_reset_fault", {"device_id": "vfd_belt"})


def test_vfd_get_status_returns_data() -> None:
    presenter, sender = make_presenter()
    sender.request_command.return_value = {
        "status": "ok",
        "vfd": {"running": True, "out_freq_hz": 50.0},
    }
    results: list = []
    presenter.vfd_get_status("vfd_belt", results.append)
    assert len(results) == 1
    assert "vfd" in results[0]


def test_degraded_without_sender() -> None:
    presenter = VfdPresenter(command_sender=None, request_runner=None)
    results: list = []
    presenter.vfd_get_status("vfd_belt", results.append)
    assert results == [{}]


def test_device_describe() -> None:
    presenter, sender = make_presenter()
    sender.request_command.return_value = {
        "status": "ok",
        "entry": {"id": "vfd_belt"},
        "protocol_meta": {"cmd_freq": {"min": 0, "max": 50}},
    }
    results: list = []
    presenter.device_describe("vfd_belt", results.append)
    assert "protocol_meta" in results[0]
