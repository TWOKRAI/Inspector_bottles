# -*- coding: utf-8 -*-
"""
frontend/tests/test_qt_event_bus.py — pytest-qt тесты для QtEventBus (Task D.2).

Тестирует:
  1. test_publish_main_thread_synchronous   — синхронная доставка на main thread.
  2. test_publish_worker_thread_marshals_to_main — QRunnable publish → main thread.
  3. test_subscribe_returns_subscription    — subscribe() возвращает Subscription.
  4. test_unsubscribe_stops_callbacks       — после unsubscribe() handler не вызывается.
  5. test_qt_event_bus_satisfies_protocol   — assignment check на EventBusProtocol.

Все тесты используют qtbot fixture из pytest-qt.
qt_api = pyside6 установлен в pyproject.toml.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QRunnable, QThreadPool

from multiprocess_prototype.domain.events import ProcessAdded, ProcessRemoved
from multiprocess_prototype.domain.entities import Process
from multiprocess_prototype.domain.protocols.event_bus import EventBusProtocol
from multiprocess_prototype.frontend.qt_event_bus import QtEventBus

if TYPE_CHECKING:
    from pytest_qt import QtBot


# ==============================================================================
# Вспомогательные фабрики
# ==============================================================================


def _make_process(name: str = "p1") -> Process:
    return Process(process_name=name)


def _make_added(name: str = "p1") -> ProcessAdded:
    return ProcessAdded(process_name=name, process=_make_process(name))


def _make_removed(name: str = "p1") -> ProcessRemoved:
    return ProcessRemoved(process_name=name)


# ==============================================================================
# Test 1 — publish на main thread синхронен
# ==============================================================================


def test_publish_main_thread_synchronous(qtbot: "QtBot") -> None:  # noqa: ARG001
    """publish() на main thread вызывает handler ДО возврата из publish().

    Это гарантируется тем, что на main thread идёт прямой pass-through
    к внутреннему EventBus (не QueuedConnection).
    """
    bus = QtEventBus()
    received: list[ProcessAdded] = []

    bus.subscribe(ProcessAdded, received.append)

    event = _make_added("sync_test")
    bus.publish(event)

    # Handler вызван синхронно — сразу после publish()
    assert len(received) == 1
    assert received[0] is event
    assert received[0].process_name == "sync_test"


# ==============================================================================
# Test 2 — publish из worker thread доставляется на main thread
# ==============================================================================


def test_publish_worker_thread_marshals_to_main(qtbot: "QtBot") -> None:
    """publish() из QRunnable доставляется на main thread через QueuedConnection.

    Алгоритм:
      - Создаём QtEventBus и подписываем handler, сохраняющий id текущего потока.
      - Запускаем QRunnable, который вызывает bus.publish() из пула потоков.
      - Ждём через qtbot.waitUntil — обрабатываем queued events в event-loop.
      - Проверяем, что handler был вызван и thread совпадает с main thread.
    """
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication

    bus = QtEventBus()

    received_threads: list[QThread] = []

    def handler(event: ProcessAdded) -> None:
        # Запоминаем поток, в котором был вызван handler
        received_threads.append(QThread.currentThread())

    bus.subscribe(ProcessAdded, handler)

    # Запускаем publish из worker thread через QThreadPool
    event = _make_added("worker_test")

    class _PublishRunnable(QRunnable):
        def run(self) -> None:
            bus.publish(event)

    QThreadPool.globalInstance().start(_PublishRunnable())

    # Ждём доставки queued event (max 1 секунда)
    qtbot.waitUntil(lambda: len(received_threads) > 0, timeout=1000)

    # Handler вызван ровно один раз
    assert len(received_threads) == 1

    # Handler вызван на main thread (не на worker thread)
    main_thread = QApplication.instance().thread()
    assert received_threads[0] is main_thread, f"Ожидался main thread ({main_thread}), получен {received_threads[0]}"


# ==============================================================================
# Test 3 — subscribe() возвращает Subscription с unsubscribe()
# ==============================================================================


def test_subscribe_returns_subscription(qtbot: "QtBot") -> None:  # noqa: ARG001
    """subscribe() возвращает объект с методом unsubscribe() (Subscription Protocol).

    Проверяем наличие unsubscribe() и __enter__/__exit__ для context manager.
    """
    bus = QtEventBus()
    subscription = bus.subscribe(ProcessAdded, lambda e: None)

    # Наличие unsubscribe()
    assert hasattr(subscription, "unsubscribe"), "Subscription должен иметь unsubscribe()"
    assert callable(subscription.unsubscribe), "unsubscribe() должен быть callable"

    # Наличие context manager
    assert hasattr(subscription, "__enter__"), "Subscription должен поддерживать __enter__"
    assert hasattr(subscription, "__exit__"), "Subscription должен поддерживать __exit__"

    # Вызов unsubscribe() не бросает исключений
    subscription.unsubscribe()

    # Повторный вызов — no-op, тоже не бросает
    subscription.unsubscribe()


# ==============================================================================
# Test 4 — unsubscribe прекращает вызовы handler'а
# ==============================================================================


def test_unsubscribe_stops_callbacks(qtbot: "QtBot") -> None:  # noqa: ARG001
    """После subscription.unsubscribe() handler больше не вызывается.

    Сценарий:
      - Подписываем handler → publish → handler вызван.
      - unsubscribe() → publish → handler не вызывается снова.
    """
    bus = QtEventBus()
    received: list[ProcessAdded] = []

    subscription = bus.subscribe(ProcessAdded, received.append)

    # До unsubscribe
    bus.publish(_make_added("before"))
    assert len(received) == 1
    assert received[0].process_name == "before"

    # Отписываемся
    subscription.unsubscribe()

    # После unsubscribe — handler не вызывается
    bus.publish(_make_added("after"))
    assert len(received) == 1  # Не изменилось

    # Context manager вариант тоже работает
    received_cm: list[ProcessAdded] = []
    with bus.subscribe(ProcessAdded, received_cm.append):
        bus.publish(_make_added("inside"))
        assert len(received_cm) == 1

    # После выхода из with — handler отписан
    bus.publish(_make_added("outside"))
    assert len(received_cm) == 1  # Не изменилось


# ==============================================================================
# Test 5 — QtEventBus удовлетворяет EventBusProtocol (assignment check)
# ==============================================================================


def test_qt_event_bus_satisfies_protocol(qtbot: "QtBot") -> None:  # noqa: ARG001
    """QtEventBus соответствует EventBusProtocol — assignment check проходит.

    Это статическая проверка на уровне Protocol, подтверждённая runtime.
    Гарантирует, что QtEventBus можно безопасно использовать в AppServices.events.
    """
    # Assignment check: mypy/pyright не ругаются, а runtime не бросает исключений
    bus_impl = QtEventBus()
    bus: EventBusProtocol = bus_impl  # type: ignore[assignment]  # noqa: F841

    # Дополнительно проверяем, что оба метода Protocol реально работают
    assert callable(bus.publish), "publish должен быть callable"
    assert callable(bus.subscribe), "subscribe должен быть callable"

    # Проверяем publish + subscribe работают вместе (smoke)
    received: list[ProcessRemoved] = []
    sub = bus.subscribe(ProcessRemoved, received.append)
    bus.publish(_make_removed("protocol_test"))

    assert len(received) == 1
    assert received[0].process_name == "protocol_test"

    sub.unsubscribe()
