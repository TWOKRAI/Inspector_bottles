# -*- coding: utf-8 -*-
"""Ф0.9 — floor ошибок, вариант B: синхронно, в одно место, без дублей.

План: plans/observability-unified-routing.md, задача 0.9 + инвариант 1.

Что доказывается:
  1. error/critical НЕ буферизуются — запись синхронна;
  2. при нуле живых приёмников запись всё равно оказывается на диске (floor);
  3. дублей нет: пока канал жив, floor пуст;
  4. запись полная — traceback и extra не усечены;
  5. пара на убитом процессе: до фикса записи нет, после есть.
"""

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

import pytest

from multiprocess_framework.modules.logger_module.core.error_floor import (
    FLOOR_FILE_NAME,
    reset_error_floors,
)
from multiprocess_framework.modules.logger_module.core.log_config import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
    LogLevel,
    LogScope,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.logger_module.channels.log_channel import LogChannel
from multiprocess_framework.modules.channel_routing_module.levels import is_error_level

_CHILD = Path(__file__).parent / "_crash_log_child.py"
_CRASH_MARKER = "URGENT-FLUSH-CRASH-MARKER"
_TRACEBACK_MARKER = "_deliberate_boom"

#: Корень репозитория: пакет ``multiprocess_framework`` резолвится оттуда.
#: В самом прогоне его в sys.path кладёт pytest (пакет-цепочка от modules/conftest.py),
#: но у дочернего процесса своего pytest нет, а ``python script.py`` кладёт в sys.path
#: каталог скрипта, а не cwd — поэтому корень передаётся явным PYTHONPATH.
_REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(autouse=True)
def _isolate_floors() -> Iterator[None]:
    """Полы — процесс-wide реестр; между тестами он обязан быть чистым."""
    reset_error_floors()
    yield
    reset_error_floors()


def _child_env() -> Dict[str, str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{_REPO_ROOT}{os.pathsep}{existing}" if existing else str(_REPO_ROOT)
    return env


class _RecordingBuffer:
    """Подставной BatchBuffer — видно, что именно в него положили."""

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


def _config(tmp_path: Path, *, with_channel: bool = True) -> LoggerManagerConfig:
    channels = {}
    scope_channels: List[str] = []
    if with_channel:
        channels["system_file"] = LoggerChannelSchema(
            name="system_file", type="file", enabled=True, file_path="system.log", rotate=False
        )
        scope_channels = ["system_file"]
    return LoggerManagerConfig(
        app_name="floor_unit",
        log_directory=str(tmp_path),
        enable_batching=True,
        batch_size=10_000,
        batch_interval=600.0,
        modules={},
        channels=channels,
        scopes={
            scope: LoggerScopeSchema(enabled=True, min_level="DEBUG", channels=scope_channels)
            for scope in ("SYSTEM", "BUSINESS", "DEBUG")
        },
    )


@contextmanager
def _logger(tmp_path: Path, *, with_channel: bool = True) -> Iterator[LoggerManager]:
    manager = LoggerManager(manager_name="FloorLogger", config=_config(tmp_path, with_channel=with_channel))
    try:
        yield manager
    finally:
        manager.shutdown()


def _floor_lines(tmp_path: Path) -> List[dict]:
    floor = tmp_path / FLOOR_FILE_NAME
    if not floor.exists():
        return []
    return [json.loads(line) for line in floor.read_text(encoding="utf-8").splitlines() if line.strip()]


# =============================================================================
# 1. Предикат аварийности
# =============================================================================


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (LogLevel.DEBUG, False),
        (LogLevel.INFO, False),
        (LogLevel.WARNING, False),
        (LogLevel.ERROR, True),
        (LogLevel.CRITICAL, True),
    ],
)
def test_is_error_level(level: LogLevel, expected: bool) -> None:
    """Граница ровно на ERROR: WARNING ещё батчится, ERROR — уже нет."""
    assert is_error_level(level) is expected
    assert is_error_level(level.value) is expected


def test_unknown_level_is_not_error() -> None:
    """Неизвестный уровень не должен молча получать синхронный путь."""
    assert is_error_level("TRACE") is False


# =============================================================================
# 2. error/critical не буферизуются, обычные записи — буферизуются
# =============================================================================


def test_error_bypasses_buffer(tmp_path: Path) -> None:
    with _logger(tmp_path) as manager:
        buffer = _RecordingBuffer()
        manager._buffer = buffer

        manager.error("boom", module="unit")

        assert buffer.calls == [], "ERROR не имеет права оказаться в пачке"
        assert "system_file" in buffer.flushed, "пачка канала должна быть сброшена ДО записи ошибки"


def test_critical_bypasses_buffer(tmp_path: Path) -> None:
    with _logger(tmp_path) as manager:
        buffer = _RecordingBuffer()
        manager._buffer = buffer

        manager.critical("boom", module="unit")

        assert buffer.calls == []


def test_info_still_buffered(tmp_path: Path) -> None:
    """Регресс-страж: батчинг обычных записей не должен исчезнуть."""
    with _logger(tmp_path) as manager:
        buffer = _RecordingBuffer()
        manager._buffer = buffer

        manager.info("routine", module="unit")

        assert [ch for ch, _ in buffer.calls] == ["system_file"]
        assert buffer.flushed == [], "обычная запись не должна дёргать сброс"


def test_error_lands_on_disk_synchronously(tmp_path: Path) -> None:
    """Без всякого flush/shutdown запись обязана уже быть в файле."""
    with _logger(tmp_path) as manager:
        manager.error(_CRASH_MARKER, module="unit")

        assert _CRASH_MARKER in (tmp_path / "system.log").read_text(encoding="utf-8")


def test_error_is_synchronous_even_with_priority_flush_off(tmp_path: Path) -> None:
    """Страж обещания README (Ф0.2): синхронность ошибок не зависит от priority_flush.

    До Ф0.9 немедленность ошибок формально приписывалась именно этому параметру
    ``BatchBuffer`` — и это было неправдой, потому что приоритет в буфер никто
    не передавал. Теперь ошибки в буфер не попадают вовсе, значит выключенный
    ``priority_flush`` обязан ничего не менять. Если кто-то вернёт ошибки в
    пачку, этот тест покраснеет вместе с текстом README.
    """
    from multiprocess_framework.modules.channel_routing_module.buffers.batch_buffer import (
        BatchBuffer,
        BatchConfig,
    )

    with _logger(tmp_path) as manager:
        manager._buffer = BatchBuffer(
            flush_fn=manager._flush_batch,
            config=BatchConfig(max_size=10_000, flush_interval=600.0, priority_flush=False),
        )

        manager.error(_CRASH_MARKER, module="unit")

        assert _CRASH_MARKER in (tmp_path / "system.log").read_text(encoding="utf-8")


def test_order_preserved_context_before_error(tmp_path: Path) -> None:
    """Контекст перед падением ложится на диск РАНЬШЕ самой ошибки."""
    with _logger(tmp_path) as manager:
        for i in range(3):
            manager.info(f"routine {i}", module="unit")
        manager.error(_CRASH_MARKER, module="unit")

        content = (tmp_path / "system.log").read_text(encoding="utf-8")
        assert content.index("routine 0") < content.index("routine 2") < content.index(_CRASH_MARKER)


# =============================================================================
# 3. Floor: срабатывает при нуле приёмников и НЕ срабатывает при живом канале
# =============================================================================


def test_no_floor_while_channel_alive(tmp_path: Path) -> None:
    """Дублей нет: пока канал пишет, floor пуст (это отличие B от A)."""
    with _logger(tmp_path) as manager:
        manager.error(_CRASH_MARKER, module="unit")

        assert _floor_lines(tmp_path) == []
        assert manager.stats["errors_to_floor"] == 0


def test_floor_catches_error_when_no_channels_configured(tmp_path: Path) -> None:
    """Конфиг без единого приёмника — запись всё равно на диске."""
    with _logger(tmp_path, with_channel=False) as manager:
        manager.error(_CRASH_MARKER, module="unit")

        lines = _floor_lines(tmp_path)
        assert len(lines) == 1
        assert lines[0]["message"] == _CRASH_MARKER
        assert manager.stats["errors_to_floor"] == 1


def test_floor_catches_error_after_sink_disabled(tmp_path: Path) -> None:
    """Живой сценарий: канал сняли через logger.sink.disable на лету."""
    with _logger(tmp_path) as manager:
        manager.error("before disable", module="unit")
        assert _floor_lines(tmp_path) == []

        assert manager.set_sink_enabled("system_file", False) is True
        manager.error(_CRASH_MARKER, module="unit")

        lines = _floor_lines(tmp_path)
        assert [line["message"] for line in lines] == [_CRASH_MARKER]


def test_floor_is_not_used_for_warning(tmp_path: Path) -> None:
    """WARNING — не crash-лог: он не обязан переживать выключенные приёмники."""
    with _logger(tmp_path, with_channel=False) as manager:
        manager.warning("just a warning", module="unit")

        assert _floor_lines(tmp_path) == []


def test_floor_record_is_complete(tmp_path: Path) -> None:
    """Запись не усечена: extra и многострочный текст доезжают целиком."""
    with _logger(tmp_path, with_channel=False) as manager:
        manager.log(
            LogScope.SYSTEM,
            LogLevel.CRITICAL,
            f"{_CRASH_MARKER}\nline two\nline three",
            module="unit",
            camera_id="cam-7",
            seq_id=42,
        )

        (record,) = _floor_lines(tmp_path)
        assert record["level"] == "CRITICAL"
        assert record["module"] == "unit"
        assert "line three" in record["message"]
        assert record["extra"]["camera_id"] == "cam-7"
        assert record["extra"]["seq_id"] == 42


def test_floor_path_falls_back_to_channel_directory(tmp_path: Path) -> None:
    """log_directory нет (так прод строит ErrorManager) → floor рядом с логами,
    но в СВОЁМ подкаталоге процесса.

    Иначе пол уехал бы в системный temp, а искать его будут в каталоге логов.

    ПРАВКА ПО РЕВЬЮ Ф0.9. Раньше тест требовал, чтобы floor лёг ПРЯМО в каталог
    логов, — и закреплял тем самым дефект: прод отдаёт всем процессам один и
    тот же абсолютный каталог, поэтому floor'ы всех процессов сходились в один
    файл. Дозапись в него не атомарна: 4 процесса × 300 записей давали ~9-11 %
    потерь и битые строки JSONL — в приёмнике последней инстанции. Теперь путь
    разведён по процессам, и тест проверяет именно это.
    """
    logs = tmp_path / "logs"
    logs.mkdir()
    config = LoggerManagerConfig(
        app_name="floor_pathcheck",
        log_directory=None,
        enable_batching=False,
        modules={},
        channels={
            "errors_file": LoggerChannelSchema(
                name="errors_file",
                type="file",
                enabled=True,
                file_path=str(logs / "errors.log"),
                rotate=False,
            )
        },
        scopes={"SYSTEM": LoggerScopeSchema(enabled=True, min_level="DEBUG", channels=["errors_file"])},
    )
    manager = LoggerManager(manager_name="PathLogger", config=config)
    try:
        floor_dir = Path(manager._resolve_floor_path()).parent
        assert floor_dir.parent == logs, "пол обязан лежать в каталоге логов, а не в системном temp"
        assert floor_dir != logs, (
            "пол обязан лежать в СВОЁМ подкаталоге: общий каталог сводит floor'ы всех "
            "процессов в один файл, дозапись в который не атомарна"
        )
    finally:
        manager.shutdown()


# =============================================================================
# 4. Реентерабельность и отношение floor ↔ tap
# =============================================================================


class _ReentrantChannel(LogChannel):
    """Канал, который САМ логирует ошибку при попытке записи.

    Худший случай для синхронного пути: ``_write_error_record`` зовёт
    ``buffer.flush()``, тот выкладывает пачку в ``_flush_batch`` → ``ch.write()``,
    а канал изнутри записи снова заходит в ``log()``. Если бы ``BatchBuffer``
    держал свой lock во время ``flush_fn``, это был бы дедлок.

    Наследует ``LogChannel``, а не утиный тип: ``ChannelRegistry.register``
    проверяет ``isinstance(channel, IChannel)`` и утку молча отвергает
    (первая редакция теста на этом и провалилась — канал не получил ничего).
    """

    def __init__(self) -> None:
        super().__init__(LoggerChannelSchema(name="reentrant", type="file", enabled=True))
        self.writes: List[Dict[str, Any]] = []
        self._manager: Any = None
        self._depth = 0

    def bind(self, manager: Any) -> None:
        self._manager = manager

    def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self.writes.append(record)
        # Заходим обратно в логгер ровно один раз — иначе тест сам себя зациклит,
        # а проверяем мы отсутствие дедлока, а не отсутствие бесконечной рекурсии
        # в заведомо самоубийственном канале.
        if self._manager is not None and self._depth == 0:
            self._depth += 1
            self._manager.error("ошибка изнутри записи в канал", module="reentrant")
        return record


def test_reentrant_channel_does_not_deadlock(tmp_path: Path) -> None:
    """Запись, порождающая запись, не должна вешать поток.

    ``BatchBuffer._flush_channel`` отдаёт пачку и ОТПУСКАЕТ lock до вызова
    flush_fn — на этом держится безопасность. Тест фиксирует это свойство:
    если кто-то занесёт flush_fn под lock, тест повиснет и упадёт по таймауту.
    """
    with _logger(tmp_path) as manager:
        channel = _ReentrantChannel()
        channel.bind(manager)
        manager._channel_registry.register(channel)
        manager.config.scopes["SYSTEM"].channels = ["reentrant"]
        manager.invalidate_decision_cache()

        manager.error(_CRASH_MARKER, module="unit")

        # Обе записи дошли: внешняя и та, что канал породил изнутри.
        messages = [record["message"] for record in channel.writes]
        assert _CRASH_MARKER in messages
        assert "ошибка изнутри записи в канал" in messages


def test_tap_and_floor_are_different_planes(tmp_path: Path) -> None:
    """Tap получает запись всегда; floor — только вместо канала, не вдобавок.

    ``_emit_to_taps`` стоит ДО записи в канал, поэтому подписчики (стор, live-хвост)
    видят ошибку независимо от судьбы канала. Это НЕ дубль в смысле инварианта:
    tap — другая плоскость (история и подписка), а floor замещает именно канал.
    Инвариант «без дублей» про то, что floor не добавляет ВТОРУЮ файловую копию
    к успешно записавшему каналу — и это проверено отдельно.
    """
    received: List[Dict[str, Any]] = []

    class _Tap:
        name = "probe"

        def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
            received.append(record)
            return record

        def close(self) -> None:
            pass

    with _logger(tmp_path, with_channel=False) as manager:
        manager.add_tap(_Tap(), min_level=LogLevel.ERROR, name="probe")

        manager.error(_CRASH_MARKER, module="unit")

        assert [r["message"] for r in received] == [_CRASH_MARKER]
        assert [r["message"] for r in _floor_lines(tmp_path)] == [_CRASH_MARKER]

    # Обратная половина: канал жив → tap получил, floor пуст.
    other = tmp_path / "alive"
    other.mkdir()
    received.clear()
    with _logger(other) as manager:
        manager.add_tap(_Tap(), min_level=LogLevel.ERROR, name="probe")

        manager.error(_CRASH_MARKER, module="unit")

        assert [r["message"] for r in received] == [_CRASH_MARKER]
        assert _floor_lines(other) == []


# =============================================================================
# 5. Пара «болезнь воспроизведена → исчезла» на убитом процессе
# =============================================================================


def _run_child_and_kill(mode: str, log_dir: Path, sinks: str = "with-sinks") -> None:
    """Поднять дочерний процесс, дождаться записи ошибки, убить без cleanup."""
    proc = subprocess.Popen(
        [sys.executable, str(_CHILD), mode, str(log_dir), sinks],
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
            pytest.fail(f"дочерний процесс не дошёл до записи ошибки: {ready!r} / {err!r}")

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


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_crash_pair_baseline_loses_the_record(tmp_path: Path) -> None:
    """Болезнь: пока ошибка шла через пачку, она умирала вместе с процессом."""
    _run_child_and_kill("baseline", tmp_path)

    everything = _read(tmp_path / "errors.log") + _read(tmp_path / FLOOR_FILE_NAME)
    assert _CRASH_MARKER not in everything, (
        "запись пережила kill в baseline — значит пара ничего не доказывает (сбросил какой-то другой триггер)"
    )


def test_crash_pair_fixed_keeps_the_record_with_traceback(tmp_path: Path) -> None:
    """Лечение: та же ошибка на диске, и она несёт traceback, а не огрызок."""
    _run_child_and_kill("fixed", tmp_path)

    content = _read(tmp_path / "errors.log")
    assert _CRASH_MARKER in content
    assert _TRACEBACK_MARKER in content, "traceback усечён — требование владельца нарушено"
    assert "routine before crash 4" in content, "контекст перед падением не доехал"


def test_crash_pair_survives_without_any_error_sink(tmp_path: Path) -> None:
    """Конфиго-независимость на живом процессе: приёмников нет, запись есть."""
    _run_child_and_kill("fixed", tmp_path, sinks="nosinks")

    floor = _read(tmp_path / FLOOR_FILE_NAME)
    assert _CRASH_MARKER in floor
    assert _TRACEBACK_MARKER in floor
