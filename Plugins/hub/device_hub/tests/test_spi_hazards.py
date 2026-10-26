"""Тесты автора SPI хаба, опасные места «Отключить»: замок и порядок вокруг ``request_disconnect`` (свойства 13 и 29).

Purpose:
    Два теста на инъекции, которые пережили слепую приёмку и тесты автора (матрица инъекций SPI, строки 13 и 29):
    ``request_disconnect`` драйвера зовётся под ``_workers_lock`` и ДО постановки ``disconnect`` в очередь
    подключений; отчёт об его отказе уходит в health ВНЕ замка. Состояние замка и очереди читается в момент вызова
    (``Lock.locked()``, снимок ``queue.Queue.queue``), а не по итогу: порядок видно только в этот момент.
    Обвязка — ``Rig`` слепой приёмки (настоящий плагин на ``make_ctx`` и ``CommandManager``).

Public API:
    Только тесты ``test_*``.

Stability: lite
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from Plugins.hub.device_hub.tests.test_spi_commands_acceptance import FakeDriver, RaisingRequestDriver, Rig

_DISCONNECT_ITEM = ("disconnect", "r1")


class ProbedRequestDriver(FakeDriver):
    """``request_disconnect()`` зовёт ``probe`` (если задан): тест снимает замок и очередь в этот момент."""

    probe: Callable[[], None] | None = None

    def request_disconnect(self) -> None:
        if self.probe is not None:
            self.probe()


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    made = Rig(tmp_path, monkeypatch)
    yield made
    made.close()


def _queued(rig: Rig) -> list[Any]:
    """Снимок очереди подключений супервизора (элементы ``(операция, device_id)``)."""
    return list(rig.plugin._conn_queue.queue)


def test_request_disconnect_runs_under_workers_lock_before_disconnect_is_queued(rig: Rig) -> None:
    """Свойство 13: в момент ``request_disconnect`` замок ``_workers_lock`` взят, ``disconnect`` в очереди ещё нет."""
    rig.factory("robot", lambda entry, proto: ProbedRequestDriver(entry, proto))
    rig.upsert("r1", "robot", "delta_universal3")
    assert rig.connect("r1") is True
    seen: dict[str, Any] = {}

    def probe() -> None:
        seen["locked"] = rig.plugin._workers_lock.locked()
        seen["queue"] = _queued(rig)

    rig.driver("r1").probe = probe

    res = rig.cmd("device_disconnect", {"device_id": "r1"})

    assert res == {"status": "ok", "conn": "disconnecting"}, res
    assert seen["locked"] is True, "request_disconnect вызван вне _workers_lock"
    assert _DISCONNECT_ITEM not in seen["queue"], f"disconnect уже в очереди до request_disconnect: {seen['queue']}"
    assert _queued(rig).count(_DISCONNECT_ITEM) == 1, _queued(rig)


def test_request_disconnect_failure_is_reported_outside_workers_lock(rig: Rig) -> None:
    """Свойство 29: ``request_disconnect`` бросил — ``report_error`` вызван один раз и вне ``_workers_lock``."""
    rig.factory("robot", lambda entry, proto: RaisingRequestDriver(entry, proto))
    rig.upsert("r1", "robot", "delta_universal3")
    assert rig.connect("r1") is True
    locked_at_report: list[bool] = []

    def report_error(*_args: Any, **_kwargs: Any) -> None:
        locked_at_report.append(rig.plugin._workers_lock.locked())

    rig.ctx.health.report_error.side_effect = report_error

    res = rig.cmd("device_disconnect", {"device_id": "r1"})

    assert res == {"status": "ok", "conn": "disconnecting"}, res
    assert locked_at_report == [False], f"report_error под замком или не один раз: {locked_at_report}"
    assert _queued(rig).count(_DISCONNECT_ITEM) == 1, _queued(rig)
