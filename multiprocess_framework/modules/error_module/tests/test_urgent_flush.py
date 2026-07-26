# -*- coding: utf-8 -*-
"""Ф0.1 — severity-путь ErrorManager отдаёт ERROR/CRITICAL в буфер как "urgent".

План: plans/observability-unified-routing.md, задача 0.1.

``ErrorManager.log()`` — полный override: для WARNING/ERROR/CRITICAL он НЕ зовёт
``LoggerCore.log()``, а собирает запись и кладёт в буфер сам. Значит фикс
приоритета в logger_core на этот путь не распространяется, и его надо
доказывать отдельно — иначе ровно ошибки (то, ради чего задача) остались бы
в пачке.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

from multiprocess_framework.modules.logger_module.core.log_config import LoggerManagerConfig
from multiprocess_framework.modules.logger_module.log_enums import (
    NORMAL_PRIORITY,
    URGENT_PRIORITY,
)

from ..core.error_manager import ErrorManager


def _file_ch(path: str) -> dict:
    return {
        "type": "file",
        "enabled": True,
        "file_path": path,
        "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        "max_size": 10 * 1024 * 1024,
        "backup_count": 5,
    }


def _config(tmp_path) -> LoggerManagerConfig:
    channels = {
        "errors_file": _file_ch(str(tmp_path / "errors.log")),
        "critical_file": _file_ch(str(tmp_path / "critical.log")),
        "warnings_file": _file_ch(str(tmp_path / "warnings.log")),
    }
    return LoggerManagerConfig.model_validate(
        {
            "app_name": "err_urgent_test",
            "default_level": "DEBUG",
            "enable_batching": True,
            "batch_size": 10_000,
            "batch_interval": 600.0,
            "channels": channels,
            "scopes": {
                "SYSTEM": {"enabled": True, "min_level": "DEBUG", "channels": list(channels)},
                "BUSINESS": {"enabled": True, "min_level": "DEBUG", "channels": ["errors_file"]},
                "DEBUG": {"enabled": True, "min_level": "DEBUG", "channels": ["errors_file"]},
            },
        }
    )


class _RecordingBuffer:
    """Подставной BatchBuffer — запоминает приоритет каждого enqueue."""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, Dict[str, Any], str]] = []

    def enqueue(self, channel: str, data: Dict[str, Any], priority: str = "normal") -> None:
        self.calls.append((channel, data, priority))

    def start(self) -> None:  # pragma: no cover — lifecycle менеджера
        pass

    def stop(self) -> None:  # pragma: no cover — lifecycle менеджера
        pass

    def flush(self, channel: str | None = None) -> None:  # pragma: no cover
        pass


def _manager_with_recording_buffer(tmp_path) -> Tuple[ErrorManager, _RecordingBuffer]:
    em = ErrorManager(config=_config(tmp_path))
    em.initialize()
    # initialize() поднял НАСТОЯЩИЙ BatchBuffer с таймер-потоком. Его надо
    # остановить ДО подмены: иначе демон-поток остаётся сиротой (shutdown()
    # остановит уже мок), а осиротевшие таймеры — известный источник флейков.
    if em._buffer is not None:
        em._buffer.stop()
    buffer = _RecordingBuffer()
    em._buffer = buffer
    return em, buffer


@pytest.mark.parametrize(
    ("method", "expected_channel"),
    [
        ("error", "errors_file"),
        ("critical", "critical_file"),
    ],
)
def test_severity_path_enqueues_urgent(tmp_path, method: str, expected_channel: str) -> None:
    em, buffer = _manager_with_recording_buffer(tmp_path)
    try:
        getattr(em, method)("boom")

        assert buffer.calls, f"{method}() не дошёл до буфера"
        channels = {channel for channel, _, _ in buffer.calls}
        assert channels == {expected_channel}
        assert all(priority == URGENT_PRIORITY for _, _, priority in buffer.calls)
    finally:
        em.shutdown()


def test_severity_path_warning_stays_normal(tmp_path) -> None:
    """WARNING идёт тем же override-путём, но батчинг ему не мешает."""
    em, buffer = _manager_with_recording_buffer(tmp_path)
    try:
        em.warning("just a warning")

        assert buffer.calls
        assert all(priority == NORMAL_PRIORITY for _, _, priority in buffer.calls)
    finally:
        em.shutdown()


def test_debug_info_fall_through_to_logger_core(tmp_path) -> None:
    """DEBUG/INFO уходят в scope-путь родителя — и там приоритет тоже normal."""
    em, buffer = _manager_with_recording_buffer(tmp_path)
    try:
        em.info("routine")

        assert buffer.calls, "INFO не дошёл до буфера через LoggerCore.log()"
        assert all(priority == NORMAL_PRIORITY for _, _, priority in buffer.calls)
    finally:
        em.shutdown()


def test_log_exception_is_urgent(tmp_path) -> None:
    """Трейсбек исключения — самая ценная запись; она не должна ждать пачку."""
    em, buffer = _manager_with_recording_buffer(tmp_path)
    try:
        try:
            raise ValueError("boom")
        except ValueError as exc:
            em.log_exception(exc, "во время обработки")

        assert buffer.calls
        assert all(priority == URGENT_PRIORITY for _, _, priority in buffer.calls)
    finally:
        em.shutdown()
