# -*- coding: utf-8 -*-
"""pytest-qt тесты QtEventBus (E2/Task 5.5 — вынос qt_event_bus во framework).

Framework-версия использует ЛОКАЛЬНЫЕ generic-события (не прототип-домен) —
это доказывает, что мост развязан от `ProjectEvent` (type-bound → generic).

Тестирует:
  1. синхронная доставка на main thread;
  2. **cross-thread publish** (QRunnable → main thread) — acceptance 5.5;
  3. subscribe() → Subscription;
  4. unsubscribe прекращает вызовы;
  5. QtEventBus удовлетворяет event_module.EventBusProtocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QRunnable, QThreadPool

from multiprocess_framework.modules.event_module import EventBusProtocol
from multiprocess_framework.modules.frontend_module.qt_event_bridge import QtEventBus

if TYPE_CHECKING:
    from pytest_qt import QtBot


# Локальные generic-события: мост не знает про прототип-union ProjectEvent.
@dataclass(frozen=True)
class _Added:
    name: str


@dataclass(frozen=True)
class _Removed:
    name: str


def test_publish_main_thread_synchronous(qtbot: "QtBot") -> None:  # noqa: ARG001
    """publish() на main thread вызывает handler синхронно (pass-through)."""
    bus = QtEventBus()
    received: list[_Added] = []
    bus.subscribe(_Added, received.append)

    event = _Added("sync_test")
    bus.publish(event)

    assert len(received) == 1
    assert received[0] is event


def test_publish_worker_thread_marshals_to_main(qtbot: "QtBot") -> None:
    """publish() из QRunnable доставляется на main thread через QueuedConnection.

    Acceptance 5.5: cross-thread publish.
    """
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication

    bus = QtEventBus()
    received_threads: list[QThread] = []

    def handler(event: _Added) -> None:  # noqa: ARG001
        received_threads.append(QThread.currentThread())

    bus.subscribe(_Added, handler)

    event = _Added("worker_test")

    class _PublishRunnable(QRunnable):
        def run(self) -> None:
            bus.publish(event)

    QThreadPool.globalInstance().start(_PublishRunnable())
    qtbot.waitUntil(lambda: len(received_threads) > 0, timeout=1000)

    assert len(received_threads) == 1
    main_thread = QApplication.instance().thread()
    assert received_threads[0] is main_thread


def test_subscribe_returns_subscription(qtbot: "QtBot") -> None:  # noqa: ARG001
    """subscribe() возвращает Subscription (unsubscribe + context manager)."""
    bus = QtEventBus()
    subscription = bus.subscribe(_Added, lambda e: None)

    assert callable(subscription.unsubscribe)
    assert hasattr(subscription, "__enter__")
    assert hasattr(subscription, "__exit__")
    subscription.unsubscribe()
    subscription.unsubscribe()  # повторно — no-op


def test_unsubscribe_stops_callbacks(qtbot: "QtBot") -> None:  # noqa: ARG001
    """После unsubscribe() handler не вызывается; context manager тоже отписывает."""
    bus = QtEventBus()
    received: list[_Added] = []
    subscription = bus.subscribe(_Added, received.append)

    bus.publish(_Added("before"))
    assert len(received) == 1

    subscription.unsubscribe()
    bus.publish(_Added("after"))
    assert len(received) == 1

    received_cm: list[_Added] = []
    with bus.subscribe(_Added, received_cm.append):
        bus.publish(_Added("inside"))
        assert len(received_cm) == 1
    bus.publish(_Added("outside"))
    assert len(received_cm) == 1


def test_qt_event_bus_satisfies_protocol(qtbot: "QtBot") -> None:  # noqa: ARG001
    """QtEventBus соответствует event_module.EventBusProtocol."""
    bus_impl = QtEventBus()
    bus: EventBusProtocol = bus_impl  # type: ignore[assignment]  # noqa: F841

    received: list[_Removed] = []
    sub = bus.subscribe(_Removed, received.append)
    bus.publish(_Removed("protocol_test"))

    assert len(received) == 1
    assert received[0].name == "protocol_test"
    sub.unsubscribe()
