# -*- coding: utf-8 -*-
"""Live-тест F.1 (доказательство Task A.2 на живом бэкенде): close() гасит
``backend-ctl-resub`` applier-поток watch-контура на РЕАЛЬНОМ TCP-сокете.

A.2 (закрыт, ``driver.py::close()``) чинил утечку: ``close()`` останавливал
reader/сокет, но НЕ гасил ``_resub_thread`` watch-контура — daemon-поток навсегда
висел в ``q.get()``; ``DriverSession.reset()`` зовёт именно ``close()`` (не
``unwatch()``) на каждый реконнект MCP-сессии → зомби-поток на каждый цикл.
Unit-тест (``test_driver.py::TestCloseStopsApplierThread``) доказывает фикс на
``_FakeSock`` (инжекция без сети) — здесь то же самое, но ``watch_like_gui()``
поднимает контур ЧЕРЕЗ настоящее TCP-соединение к живому ProcessManager: реальный
reader-поток, реальный сокет, реальный ``resume_watch``-путь у последующих driver'ов.

Собственный порт 8786 (≥8770; ловушка «двух бэкендов» — свой порт изолирует, см.
backend_ctl/AGENTS.md, project_concurrent_backends_trap).
"""

from __future__ import annotations

import threading

import pytest

from backend_ctl.driver import BackendDriver
from backend_ctl.harness import BackendHarness

_PORT = 8786


@pytest.fixture(scope="module")
def applier_backend():
    """Свой headless-бэкенд для applier-тестов на уникальном порту."""
    harness = BackendHarness(with_base=True, port=_PORT)
    harness.start()
    try:
        yield harness
    finally:
        harness.stop()


def _alive_resub_threads() -> list:
    return [t for t in threading.enumerate() if t.name == "backend-ctl-resub" and t.is_alive()]


@pytest.mark.harness_smoke
def test_close_stops_applier_thread_on_live_socket(applier_backend) -> None:
    """watch_like_gui на реальном сокете → close() гасит backend-ctl-resub поток."""
    drv = BackendDriver(port=_PORT)
    drv.connect()
    try:
        summary = drv.watch_like_gui()
        assert summary.get("success") is True, f"watch_like_gui не success: {summary}"

        thread = drv._watch._resub_thread
        assert thread is not None and thread.is_alive(), "applier-поток не поднялся после watch_like_gui"

        drv.close()

        thread.join(timeout=5.0)
        assert not thread.is_alive(), "applier-поток backend-ctl-resub не погашен close() на живом сокете"
        assert drv._watch._resub_thread is None

        # Идемпотентность: повторный close на уже закрытом driver'е не бросает.
        drv.close()
    finally:
        drv.close()


@pytest.mark.harness_smoke
def test_reconnect_cycles_do_not_leak_resub_threads_live(applier_backend) -> None:
    """N реконнект-циклов (новый driver, watch активен) на реальном сокете — 0 живых потоков после."""
    baseline = len(_alive_resub_threads())
    for _ in range(5):
        drv = BackendDriver(port=_PORT)
        drv.connect()
        summary = drv.watch_like_gui()
        assert summary.get("success") is True, f"watch_like_gui не success: {summary}"
        assert drv._watch._resub_thread is not None and drv._watch._resub_thread.is_alive()
        drv.close()

    alive = _alive_resub_threads()
    assert len(alive) <= baseline, (
        f"живые applier-потоки после реконнект-циклов на реальном сокете: {alive} "
        f"(baseline={baseline}) — A.2 регресс (зомби-потоки накапливаются)"
    )
