# -*- coding: utf-8 -*-
"""
tests/test_event_bus.py — контракт generic EventBus (carve-out из прототипа 2026-06-18).

На ПРОИЗВОЛЬНЫХ событиях (frozen dataclass, НЕ ProjectEvent) — доказывает генеричность:
  - subscribe + publish → handler вызван
  - два subscriber'а → оба в порядке регистрации
  - exception в handler не блокирует остальных (default → logging.exception)
  - кастомный error_handler вызывается при исключении
  - unsubscribe через context manager / explicit; повторный — no-op
  - publish для типа без подписчиков — no-op
  - тип-точность: подписка на A не ловит B
  - event_bus.py не содержит Qt-импортов (pure Python)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pytest

from multiprocess_framework.modules.event_module import EventBus


@dataclass(frozen=True)
class _Added:
    name: str


@dataclass(frozen=True)
class _Removed:
    name: str


def test_subscribe_and_publish_calls_handler() -> None:
    bus = EventBus()
    received: list[_Added] = []
    bus.subscribe(_Added, received.append)
    event = _Added("proc1")
    bus.publish(event)
    assert len(received) == 1
    assert received[0] is event
    assert received[0].name == "proc1"


def test_two_subscribers_called_in_registration_order() -> None:
    bus = EventBus()
    order: list[int] = []
    bus.subscribe(_Added, lambda e: order.append(1))
    bus.subscribe(_Added, lambda e: order.append(2))
    bus.publish(_Added("x"))
    assert order == [1, 2]


def test_handler_exception_logged_does_not_block_others(caplog: pytest.LogCaptureFixture) -> None:
    bus = EventBus()
    second: list[_Added] = []

    def broken(_e: _Added) -> None:
        raise ValueError("handler error")

    bus.subscribe(_Added, broken)
    bus.subscribe(_Added, second.append)
    with caplog.at_level(logging.ERROR):
        bus.publish(_Added("x"))
    assert len(second) == 1
    assert any(r.levelno >= logging.ERROR for r in caplog.records)


def test_custom_error_handler_invoked() -> None:
    errors: list[tuple[Exception, object]] = []
    second: list[_Added] = []

    def on_error(exc: Exception, event: object) -> None:
        errors.append((exc, event))

    bus = EventBus(error_handler=on_error)

    def broken(_e: _Added) -> None:
        raise RuntimeError("boom")

    bus.subscribe(_Added, broken)
    bus.subscribe(_Added, second.append)
    event = _Added("x")
    bus.publish(event)
    assert len(errors) == 1
    assert isinstance(errors[0][0], RuntimeError)
    assert errors[0][1] is event
    assert len(second) == 1


def test_unsubscribe_via_context_manager() -> None:
    bus = EventBus()
    received: list[_Added] = []
    with bus.subscribe(_Added, received.append):
        bus.publish(_Added("inside"))
    bus.publish(_Added("outside"))
    assert len(received) == 1
    assert received[0].name == "inside"


def test_unsubscribe_explicit() -> None:
    bus = EventBus()
    received: list[_Added] = []
    sub = bus.subscribe(_Added, received.append)
    bus.publish(_Added("first"))
    assert len(received) == 1
    sub.unsubscribe()
    bus.publish(_Added("second"))
    assert len(received) == 1
    sub.unsubscribe()  # повторный — no-op


def test_publish_no_subscribers_is_noop() -> None:
    bus = EventBus()
    bus.publish(_Removed("orphan"))  # не должно падать


def test_subscribe_type_exact_not_cross() -> None:
    bus = EventBus()
    added: list[_Added] = []
    removed: list[_Removed] = []
    bus.subscribe(_Added, added.append)
    bus.subscribe(_Removed, removed.append)
    bus.publish(_Added("a"))
    bus.publish(_Removed("r"))
    assert len(added) == 1
    assert len(removed) == 1


def test_no_pyside_imports() -> None:
    path = Path(__file__).resolve().parent.parent / "event_bus.py"
    content = path.read_text(encoding="utf-8")
    assert "PySide6" not in content
    assert "PyQt" not in content
    assert "QtCore" not in content
