# -*- coding: utf-8 -*-
"""Задача 0.7 — к ошибке A не приклеивается traceback ошибки B.

``ErrorManager.log_exception(exc, ...)`` раньше брал трассу из ``traceback.format_exc()``:
она читает АКТИВНОЕ исключение, а не переданный ``exc``. Вне ``except`` получалось
``NoneType: None`` (трасса пропадала), внутри чужого ``except`` — чужая трасса.

Записи снимаются НАСТОЯЩИМ tap'ом настоящего менеджера (образец — ``test_incident_context.py``):
шпион на ``self.error`` не увидел бы, что реально уходит в запись.
"""

from __future__ import annotations

from typing import Any

import pytest

from multiprocess_framework.modules.error_module.core.error_manager import ErrorManager


class _CapturingTap:
    """Приёмник tap'а: копит записи как есть (``write(dict)``)."""

    def __init__(self, name: str = "probe_tap") -> None:
        self.name = name
        self.records: list[dict[str, Any]] = []

    @property
    def channel_type(self) -> str:
        return "probe"

    def write(self, record: dict[str, Any]) -> dict[str, Any]:
        self.records.append(dict(record))
        return {"success": True}

    def close(self) -> None:
        return None


def _manager_with_tap(tmp_path, **config_extra: Any):
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
            **config_extra,
        },
    )
    mgr.initialize()
    tap = _CapturingTap()
    mgr.add_tap(tap, min_level="DEBUG", name=tap.name)
    return mgr, tap


@pytest.fixture
def errors_with_tap(tmp_path):
    mgr, tap = _manager_with_tap(tmp_path)
    try:
        yield mgr, tap
    finally:
        mgr.remove_tap(tap.name)
        mgr.shutdown()


@pytest.fixture
def errors_with_tap_trace_off(tmp_path):
    """Тот же менеджер, но флаг ``include_stacktrace=False`` задан в КОНФИГЕ."""
    mgr, tap = _manager_with_tap(tmp_path, include_stacktrace=False)
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


def test_config_include_stacktrace_false_has_no_traceback(errors_with_tap_trace_off):
    """Флаг из конфига (без аргумента вызова) тоже гейтит трассу; исключение брошенное, лог вне except."""
    mgr, tap = errors_with_tap_trace_off
    exc = _thrown_a()
    assert exc.__traceback__ is not None

    mgr.log_exception(exc, "ctx")

    message = tap.records[-1]["message"]
    assert "Traceback" not in message


def test_cause_chain_is_printed(errors_with_tap):
    """Явная причина (``raise ... from``) печатается: в записи есть и верхнее исключение, и корень."""
    mgr, tap = errors_with_tap
    try:
        try:
            raise KeyError("root")
        except KeyError as root:
            raise ValueError("top") from root
    except ValueError as caught:
        exc = caught

    mgr.log_exception(exc, "ctx")

    message = tap.records[-1]["message"]
    assert "ValueError: top" in message
    assert "KeyError: 'root'" in message
    assert "direct cause" in message
