# -*- coding: utf-8 -*-
"""Тесты DevicesPresenter — мост sender/runner как фейки, без Qt."""

from __future__ import annotations

from unittest.mock import MagicMock

from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.presenter import (
    DevicesPresenter,
    _extract,
    _extract_top,
)


class ImmediateRunner:
    """RequestRunner-стаб: исполняет синхронно."""

    def submit(self, fn, on_result) -> None:
        on_result(fn())


def make_presenter():
    sender = MagicMock()
    runner = ImmediateRunner()
    presenter = DevicesPresenter(command_sender=sender, request_runner=runner)
    return presenter, sender


# --- device_list ---


def test_device_list_calls_request() -> None:
    presenter, sender = make_presenter()
    sender.request_command.return_value = {
        "status": "ok",
        "devices": [
            {"id": "r1", "kind": "robot"},
            {"id": "v1", "kind": "vfd"},
        ],
    }
    results: list = []
    presenter.device_list(results.append)
    sender.request_command.assert_called_once_with("devices", "device_list", {})
    assert len(results) == 1
    assert len(results[0]) == 2


def test_device_list_filters_by_kind() -> None:
    presenter, sender = make_presenter()
    sender.request_command.return_value = {
        "devices": [
            {"id": "r1", "kind": "robot"},
            {"id": "v1", "kind": "vfd"},
        ],
    }
    results: list = []
    presenter.device_list(results.append, kind="vfd")
    assert len(results[0]) == 1
    assert results[0][0]["id"] == "v1"


# --- device_upsert ---


def test_device_upsert_sends_entry() -> None:
    presenter, sender = make_presenter()
    sender.request_command.return_value = {"status": "ok"}
    entry = {"id": "new1", "name": "Тест", "kind": "robot"}
    results: list = []
    presenter.device_upsert(entry, results.append)
    sender.request_command.assert_called_once_with("devices", "device_upsert", entry)


# --- device_connect / disconnect ---


def test_device_connect_sends_id() -> None:
    presenter, sender = make_presenter()
    sender.request_command.return_value = {"status": "ok", "conn": "connecting"}
    results: list = []
    presenter.device_connect("r1", results.append)
    sender.request_command.assert_called_once_with("devices", "device_connect", {"device_id": "r1"})
    assert results[0].get("conn") == "connecting"


def test_device_disconnect_sends_id() -> None:
    presenter, sender = make_presenter()
    sender.request_command.return_value = {"status": "ok", "conn": "disconnecting"}
    presenter.device_disconnect("r1")
    sender.request_command.assert_called_once_with("devices", "device_disconnect", {"device_id": "r1"})


# --- degraded mode ---


def test_degraded_without_sender() -> None:
    presenter = DevicesPresenter(command_sender=None, request_runner=None)
    results: list = []
    presenter.device_list(results.append)
    assert results == [[]]  # пустой список устройств (default)


# --- _extract / _extract_top ---


def test_extract_top_level() -> None:
    assert _extract({"devices": [1, 2]}, "devices") == [1, 2]


def test_extract_nested() -> None:
    assert _extract({"result": {"devices": [3]}}, "devices") == [3]


def test_extract_missing() -> None:
    assert _extract({"other": 1}, "devices") is None


def test_extract_top_unwraps_result() -> None:
    resp = {"result": {"entry": "data"}, "status": "ok"}
    assert _extract_top(resp) == {"entry": "data"}


def test_extract_top_plain() -> None:
    resp = {"status": "ok", "entry": "data", "extra": True}
    assert _extract_top(resp) == resp
