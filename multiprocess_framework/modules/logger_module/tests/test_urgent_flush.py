# -*- coding: utf-8 -*-
"""Ф0.1 — ERROR/CRITICAL уходят в BatchBuffer с priority="urgent".

План: plans/observability-unified-routing.md, задача 0.1.

Болезнь: ни ``LoggerCore.log()``, ни severity-путь ``ErrorManager.log()`` не
передавали третий аргумент ``enqueue`` — приоритет всегда оставался
``"normal"``, ветка немедленного сброса в ``BatchBuffer`` была недостижима,
и окно потери crash-лога равнялось ``batch_interval``.

Здесь две проверки:
  1. unit — какой приоритет реально доезжает до буфера;
  2. пара «до/после» на живом процессе, убитом без шанса на cleanup.
"""

import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

import pytest

from multiprocess_framework.modules.logger_module.core.log_config import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
    LogLevel,
    LogScope,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.logger_module.log_enums import (
    NORMAL_PRIORITY,
    URGENT_PRIORITY,
    buffer_priority,
)

_CHILD = Path(__file__).parent / "_crash_log_child.py"
_CRASH_MARKER = "URGENT-FLUSH-CRASH-MARKER"

#: Корень репозитория: пакет ``multiprocess_framework`` резолвится оттуда.
#: В самом прогоне его в sys.path кладёт pytest (пакет-цепочка от modules/conftest.py),
#: но у дочернего процесса своего pytest нет, а ``python script.py`` кладёт в sys.path
#: каталог скрипта, а не cwd — поэтому корень передаётся явным PYTHONPATH.
_REPO_ROOT = Path(__file__).resolve().parents[4]


def _child_env() -> Dict[str, str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{_REPO_ROOT}{os.pathsep}{existing}" if existing else str(_REPO_ROOT)
    return env


class _RecordingBuffer:
    """Подставной BatchBuffer — запоминает приоритет каждого enqueue."""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, Dict[str, Any], str]] = []

    def enqueue(self, channel: str, data: Dict[str, Any], priority: str = "normal") -> None:
        self.calls.append((channel, data, priority))

    def start(self) -> None:  # pragma: no cover — вызывается lifecycle'ом менеджера
        pass

    def stop(self) -> None:  # pragma: no cover — то же
        pass

    def flush(self, channel: str | None = None) -> None:  # pragma: no cover
        pass


@contextmanager
def _logger_with_recording_buffer(tmp_path: Path) -> Iterator[Tuple[LoggerManager, _RecordingBuffer]]:
    """Логгер со всеми scope'ами на один файловый канал и подставным буфером.

    Контекст-менеджер, а не фабрика: ``FileChannel`` открывает дескриптор сразу,
    и без ``shutdown()`` он живёт до конца сессии — на Windows это ломает уборку
    ``tmp_path``.
    """
    config = LoggerManagerConfig(
        app_name="urgent_flush_unit",
        log_directory=str(tmp_path),
        enable_batching=True,
        modules={},
        channels={
            "system_file": LoggerChannelSchema(
                name="system_file",
                type="file",
                enabled=True,
                file_path="system.log",
                rotate=False,
            )
        },
        scopes={
            scope: LoggerScopeSchema(enabled=True, min_level="DEBUG", channels=["system_file"])
            for scope in ("SYSTEM", "BUSINESS", "DEBUG")
        },
    )
    manager = LoggerManager(manager_name="UnitLogger", config=config)
    buffer = _RecordingBuffer()
    manager._buffer = buffer
    try:
        yield manager, buffer
    finally:
        manager.shutdown()


# =============================================================================
# 1. Приоритет по уровню
# =============================================================================


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (LogLevel.DEBUG, NORMAL_PRIORITY),
        (LogLevel.INFO, NORMAL_PRIORITY),
        (LogLevel.WARNING, NORMAL_PRIORITY),
        (LogLevel.ERROR, URGENT_PRIORITY),
        (LogLevel.CRITICAL, URGENT_PRIORITY),
    ],
)
def test_buffer_priority_by_level(level: LogLevel, expected: str) -> None:
    """Граница ровно на ERROR: WARNING ещё ждёт пачку, ERROR — уже нет."""
    assert buffer_priority(level) == expected
    # Тот же ответ на строке — записи приходят и в строковом виде.
    assert buffer_priority(level.value) == expected


def test_unknown_level_is_not_urgent() -> None:
    """Неизвестный уровень не должен молча превращаться в urgent-шторм."""
    assert buffer_priority("TRACE") == NORMAL_PRIORITY


# =============================================================================
# 2. Приоритет доезжает до буфера через LoggerCore.log()
# =============================================================================


def test_logger_error_enqueued_as_urgent(tmp_path: Path) -> None:
    with _logger_with_recording_buffer(tmp_path) as (manager, buffer):
        manager.error("boom", module="unit")

        assert buffer.calls, "ERROR не дошёл до буфера — проверка приоритета бессмысленна"
        assert all(priority == URGENT_PRIORITY for _, _, priority in buffer.calls)


def test_logger_critical_enqueued_as_urgent(tmp_path: Path) -> None:
    with _logger_with_recording_buffer(tmp_path) as (manager, buffer):
        manager.critical("boom", module="unit")

        assert buffer.calls
        assert all(priority == URGENT_PRIORITY for _, _, priority in buffer.calls)


def test_logger_info_stays_normal(tmp_path: Path) -> None:
    """Регресс-страж: батчинг обычных записей не должен исчезнуть."""
    with _logger_with_recording_buffer(tmp_path) as (manager, buffer):
        manager.info("routine", module="unit")

        assert buffer.calls
        assert all(priority == NORMAL_PRIORITY for _, _, priority in buffer.calls)


def test_priority_is_same_for_every_channel(tmp_path: Path) -> None:
    """Запись веером по нескольким каналам — приоритет одинаков у всех."""
    config = LoggerManagerConfig(
        app_name="urgent_flush_fanout",
        log_directory=str(tmp_path),
        enable_batching=True,
        modules={},
        channels={
            "system_file": LoggerChannelSchema(
                name="system_file", type="file", enabled=True, file_path="system.log", rotate=False
            ),
            "second_file": LoggerChannelSchema(
                name="second_file", type="file", enabled=True, file_path="second.log", rotate=False
            ),
        },
        scopes={"SYSTEM": LoggerScopeSchema(enabled=True, min_level="DEBUG", channels=["system_file", "second_file"])},
    )
    manager = LoggerManager(manager_name="FanoutLogger", config=config)
    buffer = _RecordingBuffer()
    manager._buffer = buffer
    try:
        manager.log(LogScope.SYSTEM, LogLevel.ERROR, "boom", module="unit")

        assert {channel for channel, _, _ in buffer.calls} == {"system_file", "second_file"}
        assert all(priority == URGENT_PRIORITY for _, _, priority in buffer.calls)
    finally:
        manager.shutdown()


# =============================================================================
# 3. Пара «болезнь воспроизведена → исчезла» на убитом процессе
# =============================================================================


def _run_child_and_kill(mode: str, log_dir: Path) -> str:
    """Поднять дочерний процесс, дождаться записи ERROR, убить без cleanup.

    Возвращает содержимое system.log (пустая строка, если файла нет).
    """
    proc = subprocess.Popen(
        [sys.executable, str(_CHILD), mode, str(log_dir)],
        cwd=str(_REPO_ROOT),
        env=_child_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        ready = proc.stdout.readline()
        if "logged" not in ready:
            proc.kill()
            _, err = proc.communicate(timeout=30)
            pytest.fail(f"дочерний процесс не дошёл до записи ERROR: {ready!r} / {err!r}")

        # kill(), а не terminate(): на Windows это TerminateProcess, на POSIX —
        # SIGKILL. Ни atexit, ни shutdown(), ни flush таймера не отработают.
        proc.kill()
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:  # pragma: no cover — страховка от зависшего ребёнка
            proc.kill()
            proc.wait(timeout=30)
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()

    log_file = log_dir / "system.log"
    return log_file.read_text(encoding="utf-8") if log_file.exists() else ""


def test_crash_pair_baseline_loses_the_record(tmp_path: Path) -> None:
    """Болезнь: с priority="normal" ERROR умирает вместе с процессом."""
    content = _run_child_and_kill("baseline", tmp_path)
    assert _CRASH_MARKER not in content, (
        "запись пережила kill без urgent-приоритета — значит пара ничего не доказывает "
        "(сбросил какой-то другой триггер)"
    )


def test_crash_pair_fixed_keeps_the_record(tmp_path: Path) -> None:
    """Лечение: с priority="urgent" та же запись оказывается на диске."""
    content = _run_child_and_kill("fixed", tmp_path)
    assert _CRASH_MARKER in content
