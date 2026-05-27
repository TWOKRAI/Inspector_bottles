# -*- coding: utf-8 -*-
"""
test_event_bus.py — тесты EventBus (Task B.6).

Тестирует:
  - subscribe + publish → handler вызван
  - два subscriber'а → оба вызваны в порядке регистрации
  - exception в handler не блокирует остальных (default → logging.exception)
  - кастомный error_handler вызывается при исключении
  - unsubscribe через context manager
  - explicit unsubscribe
  - publish для типа без подписчиков — no-op
  - подписка на тип B не ловит события типа A
  - EventBus не содержит Qt-импортов (pure Python)
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from ..event_bus import EventBus
from ..events import ProcessAdded, ProcessRemoved
from ..entities import Process


# ==============================================================================
# Вспомогательные фикстуры
# ==============================================================================


def _make_process(name: str = "test") -> Process:
    """Создать минимальный Process для событий."""
    return Process(process_name=name)


def _make_process_added(name: str = "test") -> ProcessAdded:
    return ProcessAdded(process_name=name, process=_make_process(name))


def _make_process_removed(name: str = "test") -> ProcessRemoved:
    return ProcessRemoved(process_name=name)


# ==============================================================================
# test_subscribe_and_publish_calls_handler
# ==============================================================================


def test_subscribe_and_publish_calls_handler() -> None:
    """subscribe + publish → handler вызван с правильным event."""
    bus = EventBus()
    received: list[ProcessAdded] = []

    bus.subscribe(ProcessAdded, received.append)
    event = _make_process_added("proc1")
    bus.publish(event)

    assert len(received) == 1
    assert received[0] is event
    assert received[0].process_name == "proc1"


# ==============================================================================
# test_two_subscribers_called_in_registration_order
# ==============================================================================


def test_two_subscribers_called_in_registration_order() -> None:
    """Два subscriber'а на один event_type → оба вызваны в порядке регистрации."""
    bus = EventBus()
    call_order: list[int] = []

    bus.subscribe(ProcessAdded, lambda e: call_order.append(1))
    bus.subscribe(ProcessAdded, lambda e: call_order.append(2))

    bus.publish(_make_process_added())

    assert call_order == [1, 2]


# ==============================================================================
# test_handler_exception_logged_does_not_block_others
# ==============================================================================


def test_handler_exception_logged_does_not_block_others(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Exception в handler 1 не блокирует handler 2. Default → logging.exception.

    Проверяем через caplog.records, что ERROR-запись появилась.
    """
    bus = EventBus()
    received_by_second: list[ProcessAdded] = []

    def broken_handler(event: ProcessAdded) -> None:
        raise ValueError("handler error")

    bus.subscribe(ProcessAdded, broken_handler)
    bus.subscribe(ProcessAdded, received_by_second.append)

    with caplog.at_level(logging.ERROR):
        bus.publish(_make_process_added())

    # Второй handler всё равно вызван
    assert len(received_by_second) == 1

    # Лог-запись с уровнем ERROR появилась (logging.exception пишет на ERROR)
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(error_records) >= 1


# ==============================================================================
# test_custom_error_handler_invoked
# ==============================================================================


def test_custom_error_handler_invoked() -> None:
    """EventBus(error_handler=my_handler) → my_handler(exc, event) вызывается
    при исключении в subscriber.
    """
    errors: list[tuple[Exception, ProcessAdded]] = []
    received_by_second: list[ProcessAdded] = []

    def my_error_handler(exc: Exception, event: ProcessAdded) -> None:  # type: ignore[type-arg]
        errors.append((exc, event))

    bus = EventBus(error_handler=my_error_handler)  # type: ignore[arg-type]

    def broken_handler(event: ProcessAdded) -> None:
        raise RuntimeError("boom")

    bus.subscribe(ProcessAdded, broken_handler)
    bus.subscribe(ProcessAdded, received_by_second.append)

    event = _make_process_added("x")
    bus.publish(event)

    # Кастомный error_handler сработал
    assert len(errors) == 1
    assert isinstance(errors[0][0], RuntimeError)
    assert errors[0][1] is event

    # Второй handler продолжил работу
    assert len(received_by_second) == 1


# ==============================================================================
# test_unsubscribe_via_context_manager
# ==============================================================================


def test_unsubscribe_via_context_manager() -> None:
    """Использование с context manager: внутри — handler работает; после exit — нет."""
    bus = EventBus()
    received: list[ProcessAdded] = []

    with bus.subscribe(ProcessAdded, received.append):
        bus.publish(_make_process_added("inside"))

    # После выхода из with — handler отписан
    bus.publish(_make_process_added("outside"))

    assert len(received) == 1
    assert received[0].process_name == "inside"


# ==============================================================================
# test_unsubscribe_explicit
# ==============================================================================


def test_unsubscribe_explicit() -> None:
    """sub.unsubscribe() → handler больше не вызывается. Повторный вызов — no-op."""
    bus = EventBus()
    received: list[ProcessAdded] = []

    sub = bus.subscribe(ProcessAdded, received.append)
    bus.publish(_make_process_added("first"))
    assert len(received) == 1

    sub.unsubscribe()
    bus.publish(_make_process_added("second"))
    assert len(received) == 1  # Не изменилось

    # Повторный unsubscribe — no-op (не должно падать)
    sub.unsubscribe()


# ==============================================================================
# test_publish_no_subscribers_is_noop
# ==============================================================================


def test_publish_no_subscribers_is_noop() -> None:
    """publish для типа без подписчиков — no-op без ошибок."""
    bus = EventBus()
    # ProcessRemoved никто не слушает — должно пройти без Exception
    bus.publish(_make_process_removed("orphan"))  # не должно падать


# ==============================================================================
# test_subscribe_subclass_not_called_for_parent_event
# ==============================================================================


def test_subscribe_subclass_not_called_for_parent_event() -> None:
    """subscribe(ProcessAdded, handler) НЕ ловит ProcessRemoved (тип-точно).

    EventBus — типовой dispatcher, не иерархический. Подписка на тип A
    не перехватывает события типа B, даже если они оба в union.
    """
    bus = EventBus()
    added_received: list[ProcessAdded] = []
    removed_received: list[ProcessRemoved] = []

    bus.subscribe(ProcessAdded, added_received.append)
    bus.subscribe(ProcessRemoved, removed_received.append)

    bus.publish(_make_process_added("proc"))
    bus.publish(_make_process_removed("proc"))

    # Каждый handler получил только свой тип
    assert len(added_received) == 1
    assert len(removed_received) == 1

    # Кросс-загрязнения нет
    assert added_received[0].process_name == "proc"
    assert removed_received[0].process_name == "proc"


# ==============================================================================
# test_no_pyside_imports
# ==============================================================================


def test_no_pyside_imports() -> None:
    """EventBus — pure Python: event_bus.py не содержит Qt-импортов."""
    event_bus_path = Path(__file__).resolve().parent.parent / "event_bus.py"
    content = event_bus_path.read_text(encoding="utf-8")

    assert "PySide6" not in content, "event_bus.py содержит PySide6-импорты"
    assert "PyQt" not in content, "event_bus.py содержит PyQt-импорты"
    assert "QtCore" not in content, "event_bus.py содержит QtCore-импорты"
