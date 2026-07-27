# -*- coding: utf-8 -*-
"""Ф0.9 — floor на severity-пути ErrorManager.

План: plans/observability-unified-routing.md, задача 0.9 + инвариант 1.

``ErrorManager.log()`` — полный override: для WARNING/ERROR/CRITICAL он НЕ зовёт
``LoggerCore.log()``, а сам решает, куда писать. Значит и синхронный путь, и
floor приходится доказывать здесь отдельно — фикс в родителе на этот путь
не распространяется. Ровно поэтому инвариант 1 плана требует править
«прицельно оба места».
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

import pytest

from multiprocess_framework.modules.logger_module.core.error_floor import (
    FLOOR_FILE_NAME,
    reset_error_floors,
)
from multiprocess_framework.modules.logger_module.core.log_config import LoggerManagerConfig

from ..core.error_manager import ErrorManager

_MARKER = "FLOOR-ERROR-MARKER"


@pytest.fixture(autouse=True)
def _isolate_floors() -> Iterator[None]:
    reset_error_floors()
    yield
    reset_error_floors()


def _file_ch(path: str) -> dict:
    return {
        "type": "file",
        "enabled": True,
        "file_path": path,
        "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        "max_size": 10 * 1024 * 1024,
        "backup_count": 5,
    }


def _config(tmp_path: Path, *, with_channels: bool = True) -> LoggerManagerConfig:
    channels: Dict[str, dict] = {}
    if with_channels:
        channels = {
            "errors_file": _file_ch(str(tmp_path / "errors.log")),
            "critical_file": _file_ch(str(tmp_path / "critical.log")),
            "warnings_file": _file_ch(str(tmp_path / "warnings.log")),
        }
    return LoggerManagerConfig.model_validate(
        {
            "app_name": "err_floor_test",
            "default_level": "DEBUG",
            "log_directory": str(tmp_path),
            "enable_batching": True,
            "batch_size": 10_000,
            "batch_interval": 600.0,
            # ВАЖНО: modules={} обязателен. Дефолт LoggerManagerConfig заводит 9
            # модульных файловых каналов, и при пустом scope.channels запись
            # уходит верером во ВСЕ зарегистрированные каналы
            # (`scope_config.channels or registry.names()`) — floor бы не сработал,
            # и тест доказывал бы не то, что заявляет.
            "modules": {},
            "channels": channels,
            "scopes": {
                "SYSTEM": {"enabled": True, "min_level": "DEBUG", "channels": list(channels)},
                "BUSINESS": {"enabled": True, "min_level": "DEBUG", "channels": list(channels)},
                "DEBUG": {"enabled": True, "min_level": "DEBUG", "channels": list(channels)},
            },
        }
    )


class _RecordingBuffer:
    def __init__(self) -> None:
        self.calls: List[Tuple[str, Dict[str, Any]]] = []
        self.flushed: List[str] = []

    def enqueue(self, channel: str, data: Dict[str, Any], priority: str = "normal") -> None:
        self.calls.append((channel, data))

    def flush(self, channel: str | None = None) -> None:
        self.flushed.append(channel or "*")

    def start(self) -> None:  # pragma: no cover — lifecycle менеджера
        pass

    def stop(self) -> None:  # pragma: no cover — lifecycle менеджера
        pass


def _manager(tmp_path: Path, *, with_channels: bool = True) -> ErrorManager:
    em = ErrorManager(config=_config(tmp_path, with_channels=with_channels))
    em.initialize()
    return em


def _floor_lines(tmp_path: Path) -> List[dict]:
    floor = tmp_path / FLOOR_FILE_NAME
    if not floor.exists():
        return []
    return [json.loads(line) for line in floor.read_text(encoding="utf-8").splitlines() if line.strip()]


# =============================================================================
# Синхронность: error/critical мимо буфера, WARNING — через буфер
# =============================================================================


@pytest.mark.parametrize("method", ["error", "critical"])
def test_severity_path_bypasses_buffer(tmp_path: Path, method: str) -> None:
    em = _manager(tmp_path)
    em._buffer.stop()
    buffer = _RecordingBuffer()
    em._buffer = buffer
    try:
        getattr(em, method)(_MARKER)

        assert buffer.calls == [], f"{method}() не имеет права оказаться в пачке"
        assert buffer.flushed, "пачка канала должна быть сброшена ДО записи ошибки"
    finally:
        em.shutdown()


def test_warning_still_buffered(tmp_path: Path) -> None:
    """WARNING идёт тем же override-путём, но остаётся батченым."""
    em = _manager(tmp_path)
    em._buffer.stop()
    buffer = _RecordingBuffer()
    em._buffer = buffer
    try:
        em.warning("just a warning")

        assert [ch for ch, _ in buffer.calls] == ["warnings_file"]
        assert buffer.flushed == []
    finally:
        em.shutdown()


def test_error_lands_on_disk_synchronously(tmp_path: Path) -> None:
    em = _manager(tmp_path)
    try:
        em.error(_MARKER)

        assert _MARKER in (tmp_path / "errors.log").read_text(encoding="utf-8")
    finally:
        em.shutdown()


def test_critical_routes_to_critical_file_synchronously(tmp_path: Path) -> None:
    em = _manager(tmp_path)
    try:
        em.critical(_MARKER)

        assert _MARKER in (tmp_path / "critical.log").read_text(encoding="utf-8")
        assert _MARKER not in (tmp_path / "errors.log").read_text(encoding="utf-8")
    finally:
        em.shutdown()


# =============================================================================
# Floor: нет приёмника → запись всё равно на диске; есть приёмник → дубля нет
# =============================================================================


def test_no_floor_while_channel_alive(tmp_path: Path) -> None:
    em = _manager(tmp_path)
    try:
        em.error(_MARKER)

        assert _floor_lines(tmp_path) == []
        assert em.stats["errors_to_floor"] == 0
    finally:
        em.shutdown()


def test_floor_catches_error_after_sink_disabled(tmp_path: Path) -> None:
    """severity-маршрут конфиго-зависим целиком — вот его страховка.

    Снимаются ВСЕ severity-каналы, а не один. Правка Ф1 (находка ревью: у ERROR
    не было запасного маршрута) достроила цепочку, и снятие одного
    ``errors_file`` теперь означает «маршрут перестроился на живой
    ``critical_file``», а не «приёмника нет». Пол — страховка на случай «нет
    ни одного», и проверять его надо ровно на этом входе; промежуточное
    состояние пинует ``test_error_plane_defaults.py::test_every_level_has_a_fallback_receiver``.
    """
    em = _manager(tmp_path)
    try:
        for name in ("errors_file", "critical_file", "warnings_file"):
            assert em.set_sink_enabled(name, False) is True
        assert em.get_stats()["level_routes"] == {}, "предусловие: приёмников не осталось"

        em.error(_MARKER)

        lines = _floor_lines(tmp_path)
        assert [line["message"] for line in lines] == [_MARKER]
        assert em.stats["errors_to_floor"] == 1
    finally:
        em.shutdown()


def test_floor_catches_error_without_any_channel(tmp_path: Path) -> None:
    """Приёмников нет вовсе: _level_to_channel пуст, путь уходит к родителю."""
    em = _manager(tmp_path, with_channels=False)
    try:
        em.error(_MARKER)

        lines = _floor_lines(tmp_path)
        assert len(lines) == 1
        assert lines[0]["message"] == _MARKER
    finally:
        em.shutdown()


def test_log_exception_keeps_full_traceback_in_floor(tmp_path: Path) -> None:
    """Требование владельца: запись полная — с трейсбеком, а не огрызок."""
    em = _manager(tmp_path, with_channels=False)
    try:
        try:
            raise ValueError(_MARKER)
        except ValueError as exc:
            em.log_exception(exc, "во время обработки", module="unit")

        (record,) = _floor_lines(tmp_path)
        assert _MARKER in record["message"]
        assert "Traceback (most recent call last)" in record["message"]
        assert "test_log_exception_keeps_full_traceback_in_floor" in record["message"]
    finally:
        em.shutdown()


def test_no_duplicate_between_channel_and_floor(tmp_path: Path) -> None:
    """Одна эмиссия = одна запись: канал ИЛИ пол, никогда оба.

    Приёмники снимаются ВСЕ — см. пояснение в
    ``test_floor_catches_error_after_sink_disabled``: после Ф1 снятие одного
    ``errors_file`` переводит ERROR на живой ``critical_file``, и «второй
    записи» просто неоткуда взяться. Проверяемое свойство (дубля нет) от этого
    не изменилось, изменился вход, на котором оно проверяется.
    """
    em = _manager(tmp_path)
    try:
        em.error(_MARKER)
        for name in ("errors_file", "critical_file", "warnings_file"):
            em.set_sink_enabled(name, False)
        em.error(f"{_MARKER}-second")

        on_disk = (tmp_path / "errors.log").read_text(encoding="utf-8")
        in_floor = [line["message"] for line in _floor_lines(tmp_path)]

        assert on_disk.count(_MARKER) == 1
        assert in_floor == [f"{_MARKER}-second"]
        assert f"{_MARKER}-second" not in on_disk
        assert f"{_MARKER}-second" not in (tmp_path / "critical.log").read_text(encoding="utf-8"), (
            "запись легла и в пол, и в запасной канал — дубль"
        )
    finally:
        em.shutdown()
