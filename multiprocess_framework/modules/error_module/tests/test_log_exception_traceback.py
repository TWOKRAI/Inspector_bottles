# -*- coding: utf-8 -*-
"""Задача 0.7 — к ошибке A не приклеивается traceback ошибки B.

``ErrorManager.log_exception(exc, ...)`` раньше брал трассу из ``traceback.format_exc()``:
она читает АКТИВНОЕ исключение, а не переданный ``exc``. Вне ``except`` получалось
``NoneType: None`` (трасса пропадала), внутри чужого ``except`` — чужая трасса.

Записи снимаются НАСТОЯЩИМ tap'ом настоящего менеджера (образец — ``test_incident_context.py``):
шпион на ``self.error`` не увидел бы, что реально уходит в запись.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.error_module.core.error_manager import ErrorManager


class _CapturingTap:
    """Приёмник tap'а: копит записи как есть (``write(dict)``)."""

    def __init__(self, name: str = "probe_tap") -> None:
        self.name = name
        self.records: List[Dict[str, Any]] = []

    @property
    def channel_type(self) -> str:
        return "probe"

    def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self.records.append(dict(record))
        return {"success": True}

    def close(self) -> None:
        return None


@pytest.fixture
def errors_with_tap(tmp_path):
    mgr = ErrorManager(
        manager_name="TracebackProbe",
        config={
            "app_name": "traceback",
            "log_directory": str(tmp_path),
            "enable_batching": False,
            "modules": {},
            "channels": {"a": {"type": "file", "enabled": True, "file_path": str(tmp_path / "a.log")}},
            "scopes": {
                "SYSTEM": {"channels": ["a"]},
                "BUSINESS": {"channels": ["a"]},
                "DEBUG": {"channels": ["a"]},
            },
        },
    )
    mgr.initialize()
    tap = _CapturingTap()
    mgr.add_tap(tap, min_level="DEBUG", name=tap.name)
    try:
        yield mgr, tap
    finally:
        mgr.remove_tap(tap.name)
        mgr.shutdown()


def _raise_a() -> None:
    raise ValueError("A-original")


def _thrown_a() -> ValueError:
    """Исключение A: брошено и поймано ДО любого чужого ``except`` (``__context__`` пуст)."""
    try:
        _raise_a()
    except ValueError as caught:
        return caught
    raise AssertionError("unreachable")


def test_outside_except_has_traceback(errors_with_tap):
    mgr, tap = errors_with_tap
    exc = _thrown_a()

    mgr.log_exception(exc, "ctx")

    message = tap.records[-1]["message"]
    assert "Traceback" in message
    assert "ValueError: A-original" in message


def test_inside_other_except_names_own_exception(errors_with_tap):
    mgr, tap = errors_with_tap
    exc = _thrown_a()

    try:
        raise KeyError("B-unrelated")
    except KeyError:
        mgr.log_exception(exc, "ctx")

    message = tap.records[-1]["message"]
    assert "ValueError: A-original" in message
    assert "KeyError: 'B-unrelated'" not in message


def test_include_stacktrace_false_has_no_traceback(errors_with_tap):
    """Характеризационный: исключение БРОШЕННОЕ, иначе «нет трассы» дала бы и ветка без __traceback__."""
    mgr, tap = errors_with_tap
    exc = _thrown_a()
    assert exc.__traceback__ is not None

    mgr.log_exception(exc, "ctx", include_stacktrace=False)

    message = tap.records[-1]["message"]
    assert "Traceback" not in message


def test_unraised_exception_has_no_traceback(errors_with_tap):
    """Характеризационный: создан-но-не-брошенный — вывод прежний, ничего не приклеивается."""
    mgr, tap = errors_with_tap

    mgr.log_exception(ValueError("x"), "ctx")

    message = tap.records[-1]["message"]
    assert message == "ctx: x"
    assert "Traceback" not in message
