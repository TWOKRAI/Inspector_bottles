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


# --------------------------------------------------------------------------- #
#  Отказ ДОСТАВКИ (не самого запроса) — Task 3.3, находка ревью F3г            #
# --------------------------------------------------------------------------- #


def test_delivery_failure_does_not_escape_run() -> None:
    """Отказ доставки результата не выпускает исключение из ``run()``.

    Что именно может сломаться: `run()` прикрывал `try` только вызов `fn()`, а
    доставку — нет. Доставка идёт Qt-сигналом, и на разрушенном источнике
    (RequestRunner уничтожен при выходе приложения, пока задача была в пуле)
    `emit` поднимает `RuntimeError: Signal source has been deleted` — уже ПОСЛЕ
    того, как запрос успешно отработал. Исключение улетало в поток пула
    необработанным, а инициатор не получал ни результата, ни признака отказа.

    Зовём `run()` напрямую, а не через пул: так отказ виден тесту как обычное
    исключение, а не как сообщение в чужом потоке, которое можно проглядеть.

    Чего этот тест НЕ утверждает: что результат всё-таки доставлен. Доставить
    по разрушенному сигналу нечем — поэтому у инициатора обязан быть свой
    дедлайн (у TelemetryPoller это выселение по TTL, ADR-139).
    """
    from multiprocess_prototype.frontend.bridge.request_runner import _RequestTask

    delivered: list[dict[str, Any]] = []

    def broken_delivery(result: dict[str, Any]) -> None:
        delivered.append(result)
        raise RuntimeError("Signal source has been deleted")

    task = _RequestTask(lambda: {"success": True, "result": "ok"}, broken_delivery)

    task.run()  # не должно бросить наружу

    assert delivered == [{"success": True, "result": "ok"}], (
        "доставка не была даже предпринята — сломано что-то другое, не то, что проверяем"
    )


def test_pool_thread_survives_delivery_failure(qtbot) -> None:
    """Поток пула переживает отказ доставки и берёт следующую задачу.

    Наблюдаемое последствие предыдущего свойства, проверенное через НАСТОЯЩИЙ
    пул: необработанное исключение в потоке пула могло бы утащить поток с
    собой, и следующая задача осталась бы без обслуживания.

    Внимание на точку отказа: здесь ломается ``on_done`` — то есть **сам
    emit**, дублёром которого он выступает (`RequestRunner.submit` передаёт
    сюда именно лямбду с `emit`). Отказ ПОЛЬЗОВАТЕЛЬСКОГО коллбэка — другая
    точка: он исполняется позже, в main thread внутри `_on_delivered`, и
    сюда не относится.
    """
    from PySide6.QtCore import QThreadPool

    from multiprocess_prototype.frontend.bridge.request_runner import _RequestTask

    pool = QThreadPool()
    pool.setMaxThreadCount(1)

    def boom(_result: dict[str, Any]) -> None:
        raise RuntimeError("Signal source has been deleted")

    pool.start(_RequestTask(lambda: {"success": True}, boom))
    assert pool.waitForDone(3000), "пул не завершил задачу с отказавшей доставкой"

    done: list[dict[str, Any]] = []
    pool.start(_RequestTask(lambda: {"success": True, "result": "alive"}, done.append))
    assert pool.waitForDone(3000), "пул не взял следующую задачу после отказа доставки"
    assert done and done[0]["result"] == "alive"
