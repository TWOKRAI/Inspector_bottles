# -*- coding: utf-8 -*-
"""Тесты команд запуска ProcessManagerProxy (Task 2.3, REDS 16).

``run_start/stop/ack/status_async`` отправляют ``{"cmd": "system.run.*"}`` через
request/response (не fire-and-forget); результат PM приходит в ``on_result``.

Запуск:
    QT_QPA_PLATFORM=offscreen pytest frontend/bridge/tests/test_process_manager_proxy_run.py -q
"""

from __future__ import annotations

import pytest

from multiprocess_prototype.frontend.bridge.process_manager_proxy import ProcessManagerProxy


class _FakeRequestingSender:
    """Fake-sender: записывает request_system_command и send_system_command."""

    def __init__(self, response: dict) -> None:
        self.sent: list[dict] = []
        self.requested: list[dict] = []
        self._response = response

    def send_system_command(self, command: dict) -> None:
        self.sent.append(command)

    def request_system_command(self, command: dict, *, timeout: float = 30.0) -> dict:
        self.requested.append(command)
        return self._response


@pytest.mark.parametrize(
    ("method", "cmd"),
    [
        ("run_start_async", "system.run.start"),
        ("run_stop_async", "system.run.stop"),
        ("run_ack_async", "system.run.ack"),
        ("run_status_async", "system.run.status"),
    ],
)
def test_run_command_goes_through_request_and_delivers_result(qtbot, method: str, cmd: str) -> None:
    """Команда уходит request'ом (не fire-and-forget), ответ PM доходит до on_result."""
    response = {"success": True, "result": {"success": True, "state": "running"}}
    sender = _FakeRequestingSender(response)
    proxy = ProcessManagerProxy(sender)
    results: list[dict] = []

    ret = getattr(proxy, method)(results.append)

    assert ret is None
    qtbot.waitUntil(lambda: len(results) == 1, timeout=2000)
    assert sender.requested == [{"cmd": cmd}]
    assert sender.sent == []
    assert results[0] == response


def test_run_refusal_delivered_as_is(qtbot) -> None:
    """Отказ PM (success False + result.error) приходит в on_result без искажений."""
    response = {"success": False, "result": {"success": False, "state": "not_ready", "error": "not_ready"}}
    sender = _FakeRequestingSender(response)
    proxy = ProcessManagerProxy(sender)
    results: list[dict] = []

    proxy.run_start_async(results.append)

    qtbot.waitUntil(lambda: len(results) == 1, timeout=2000)
    assert results[0] == response
