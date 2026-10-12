"""Слепая приёмка сводки остановки PM (lifecycle-owner-scope, Task 1.2a).

Контракт: при ``shutdown()`` группа детей получает ``request_stop`` раньше записи
сводки, сводка раньше ``flush``; повторный ``shutdown()`` без ``stop()`` не гасит
детей и не публикует сводку второй раз.

Реестр процессов подменяется ПОСЛЕ ``initialize()`` — он читается в момент остановки.
"""

from __future__ import annotations

import contextlib
import threading

from multiprocess_framework.modules.process_manager_module.core.stop_budget import stop_budget
from multiprocess_framework.modules.process_manager_module.process.process_manager_process import (
    ProcessManagerProcess,
)


def call_bounded(fn, timeout_s: float):
    """Вызвать ``fn`` в daemon-потоке; вернуть (завершился, результат, ошибка)."""
    box: dict = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 - тест сам разбирает ошибку
            box["error"] = exc

    th = threading.Thread(target=run, daemon=True, name="call_bounded")
    th.start()
    th.join(timeout_s)
    return (not th.is_alive()), box.get("result"), box.get("error")


class _Group:
    def __init__(self, journal: list) -> None:
        self._journal = journal

    def request_stop(self) -> None:
        self._journal.append("group.request_stop")

    def join_until(self, deadline: float) -> bool:
        self._journal.append("group.join_until")
        return True

    def kill(self) -> None:
        self._journal.append("group.kill")

    def close(self) -> None:
        self._journal.append("group.close")

    def result(self) -> dict:
        self._journal.append("group.result")
        return {"child": True}


class _FakeRegistry:
    def __init__(self, journal: list) -> None:
        self._journal = journal

    def children_stop(self, *, mark_reader_gone):
        self._journal.append("children_stop")
        return _Group(self._journal)

    def exit_report(self, name) -> dict:
        return {"released": 0, "buffered_dropped": 0, "reported": True}


@contextlib.contextmanager
def pm_with_fakes():
    pm = ProcessManagerProcess(config={"shutdown_timeout": 1.0})
    pm.attach_stop_budget(stop_budget(1.0))
    assert pm.initialize() is True
    journal: list = []
    summaries: list = []

    def publish_stop_summary(*args, **kwargs) -> None:
        journal.append("summary")
        summaries.append((args, kwargs))

    pm._publish_stop_summary = publish_stop_summary
    pm._flush_observability = lambda *a, **k: journal.append("flush")
    pm._process_registry = _FakeRegistry(journal)
    try:
        yield pm, journal, summaries
    finally:
        call_bounded(pm.shutdown, 15.0)


def test_pm_summary_before_flush() -> None:
    with pm_with_fakes() as (pm, journal, summaries):
        done, _, error = call_bounded(pm.shutdown, 15.0)
        assert done, "shutdown() завис"
        assert error is None, repr(error)
        assert "group.request_stop" in journal, journal
        assert "summary" in journal, journal
        assert "flush" in journal, journal
        assert journal.index("group.request_stop") < journal.index("summary") < journal.index("flush"), journal
        args, kwargs = summaries[0]
        assert {"child": True} in list(args) + list(kwargs.values()), summaries


def test_pm_shutdown_without_stop_stops_children_once() -> None:
    with pm_with_fakes() as (pm, journal, _):
        first = call_bounded(pm.shutdown, 15.0)
        second = call_bounded(pm.shutdown, 15.0)
        assert first[0] and second[0], "shutdown() завис"
        assert first[2] is None and second[2] is None, (first[2], second[2])
        assert journal.count("children_stop") == 1, journal
        assert journal.count("group.request_stop") == 1, journal
        assert journal.count("summary") == 1, journal
