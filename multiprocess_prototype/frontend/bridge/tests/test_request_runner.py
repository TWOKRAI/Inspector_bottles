# -*- coding: utf-8 -*-
"""Тесты RequestRunner — блокирующий request на worker-потоке, результат в main-thread.

command-result-bridge P2. Проверяют:
- результат fn доставляется в on_result;
- on_result исполняется в Qt main-thread (а не в потоке пула) — thread-safety;
- исключение в fn → error-result (поток пула не падает);
- не-dict результат оборачивается;
- on_result=None безопасен.

Запуск:
    python -m pytest multiprocess_prototype/frontend/bridge/tests/test_request_runner.py -v
"""

from __future__ import annotations

import threading
from typing import Any

from multiprocess_prototype.frontend.bridge.request_runner import RequestRunner


def test_submit_delivers_result(qtbot) -> None:
    """fn → результат приходит в on_result."""
    runner = RequestRunner()
    results: list[dict[str, Any]] = []

    runner.submit(lambda: {"success": True, "result": {"replaced": ["w1"]}}, results.append)

    qtbot.waitUntil(lambda: len(results) == 1, timeout=2000)
    assert results[0] == {"success": True, "result": {"replaced": ["w1"]}}


def test_on_result_runs_in_main_thread(qtbot) -> None:
    """on_result исполняется в main-thread (request — на worker, доставка — сигналом)."""
    runner = RequestRunner()
    threads: list[bool] = []  # is_main_thread на момент вызова on_result

    def on_result(_res: dict) -> None:
        threads.append(threading.current_thread() is threading.main_thread())

    # fn фиксирует, что САМ request шёл НЕ в main-thread (на потоке пула)
    fn_thread: list[bool] = []

    def fn() -> dict:
        fn_thread.append(threading.current_thread() is threading.main_thread())
        return {"success": True}

    runner.submit(fn, on_result)

    qtbot.waitUntil(lambda: len(threads) == 1, timeout=2000)
    assert threads[0] is True  # on_result — в main-thread
    assert fn_thread[0] is False  # request — НЕ в main-thread (worker пула)


def test_exception_becomes_error_result(qtbot) -> None:
    """Исключение в fn → error-result, поток пула не падает."""
    runner = RequestRunner()
    results: list[dict[str, Any]] = []

    def boom() -> dict:
        raise RuntimeError("backend boom")

    runner.submit(boom, results.append)

    qtbot.waitUntil(lambda: len(results) == 1, timeout=2000)
    assert results[0]["success"] is False
    assert "backend boom" in results[0]["error"]


def test_non_dict_result_wrapped(qtbot) -> None:
    """Не-dict результат оборачивается в {success, result}."""
    runner = RequestRunner()
    results: list[dict[str, Any]] = []

    runner.submit(lambda: "ok", results.append)

    qtbot.waitUntil(lambda: len(results) == 1, timeout=2000)
    assert results[0] == {"success": True, "result": "ok"}


def test_on_result_none_safe(qtbot) -> None:
    """on_result=None — request выполняется, доставка не падает."""
    runner = RequestRunner()
    ran: list[bool] = []

    runner.submit(lambda: ran.append(True) or {"success": True}, None)

    qtbot.waitUntil(lambda: len(ran) == 1, timeout=2000)
    # Дать событийному циклу прокрутить доставку (не должно быть исключений)
    qtbot.wait(50)
