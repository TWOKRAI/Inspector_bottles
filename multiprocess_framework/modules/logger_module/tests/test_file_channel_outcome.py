# -*- coding: utf-8 -*-
"""Task 0.4: файловый и консольный приёмник отвечают «error» на OSError.

Ошибка записи (диск полон) раньше глоталась stdlib: ``Handler.handleError``
печатал «Logging error» в stderr, а ``emit`` возвращался штатно, поэтому канал
отвечал ``success``, а счётчик показывал «записано». Теперь причина
сохраняется в хэндлере строкой, канал читает её внутри ``_emit`` и отвечает
``{"status": "error", ...}``; менеджер кладёт такой ответ в
``channel_refused_records`` и отправляет ERROR на пол ошибок.

Ошибка имитируется потоком, у которого ``write`` бросает ``OSError(28)``;
у потока есть ``tell()``: без него отказ случился бы на ``AttributeError`` в
``RotatingFileHandler.shouldRollover``, а не на ``OSError``.
"""

from __future__ import annotations

import io
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

import pytest

from multiprocess_framework.modules.logger_module.channels.log_channel import ConsoleChannel, FileChannel
from multiprocess_framework.modules.logger_module.configs.logger_manager_config import LoggerChannelSchema
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

_JOIN_DEADLINE_S = 10.0
_HAZARD_JOIN_DEADLINE_S = 60.0
_HAZARD_WRITES = 3000
_ENOSPC_TEXT = "OSError: errno 28 No space left on device"


class _EnospcStream:
    """Поток, бросающий «диск полон» на каждую запись."""

    def write(self, data: str) -> int:
        raise OSError(28, "No space left on device")

    def flush(self) -> None:
        return None

    def tell(self) -> int:
        return 0

    def seek(self, *args: Any) -> int:
        return 0


class _RaisingStream(_EnospcStream):
    """Поток, чей ``write`` бросает заданное исключение (форма ответа канала по типу ошибки)."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def write(self, data: str) -> int:
        raise self._exc


class _SelectiveStream(io.StringIO):
    """Здоровый поток, который падает только на записи с маркером ``BADREC``."""

    def write(self, data: str) -> int:
        if "BADREC" in data:
            raise OSError(28, "No space left on device")
        return super().write(data)


class _FlakyStream(io.StringIO):
    """Здоровый поток, который падает на первых ``fail_times`` записях."""

    def __init__(self, fail_times: int = 1) -> None:
        super().__init__()
        self._fail_times = fail_times

    def write(self, data: str) -> int:
        if self._fail_times > 0:
            self._fail_times -= 1
            raise OSError(28, "No space left on device")
        return super().write(data)


def _swap_stream(handler: Any, stream: Any) -> None:
    """Подменить поток хэндлера; настоящий файл закрыть (без утечки fd), консольный sys.stderr не трогать."""
    old = handler.stream
    handler.stream = stream
    if old is not None and hasattr(handler, "baseFilename"):
        old.close()


def _bounded(fn: Callable[[], Any]) -> Any:
    """Сценарий в daemon-потоке с дедлайном: зависание — красный тест, не зависший прогон."""
    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросить в поток теста
            box["exc"] = exc

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(_JOIN_DEADLINE_S)
    assert not t.is_alive(), "сценарий завис дольше дедлайна"
    if "exc" in box:
        raise box["exc"]
    return box["value"]


def _record(message: str = "payload-text") -> dict[str, Any]:
    return {
        "module": "probe",
        "level": "WARNING",
        "message": message,
        "timestamp": time.time(),
        "extra": {},
        "seq": 1,
    }


def _run_r1(tmp_path: Path, streams: Callable[[], Any]) -> dict[str, Any]:
    """Сценарий r1: все 4 канала менеджера получают ``streams()``, затем warning и error."""

    def _scenario() -> dict[str, Any]:
        lm = LoggerManager(config={"log_directory": str(tmp_path)})
        try:
            patched = 0
            for ch in lm.get_all_channels():
                _swap_stream(ch.handler, streams())
                patched += 1
            assert patched == 4, f"пропатчено каналов {patched}, ожидалось 4"
            before = lm.get_stats()
            lm.warning("w", module="probe")
            lm.error("e", module="probe")
            after = lm.get_stats()
            return {"before": before, "after": after}
        finally:
            lm.shutdown()

    return _bounded(_scenario)


def _delta(result: dict[str, Any], key: str) -> int:
    return result["after"][key] - result["before"][key]


# ---------------------------------------------------------------------------
# RED 1-4: сценарий r1 через менеджер
# ---------------------------------------------------------------------------


def test_enospc_counts_refused_records(tmp_path: Path) -> None:
    result = _run_r1(tmp_path, _EnospcStream)
    assert _delta(result, "channel_refused_records") == 4
    # канал не бросает исключение (ADR-CRM-011): счётчик исключений остаётся нулевым
    assert _delta(result, "channel_write_errors") == 0


def test_enospc_counts_nothing_written(tmp_path: Path) -> None:
    result = _run_r1(tmp_path, _EnospcStream)
    assert _delta(result, "channel_written_records") == 0


def test_enospc_error_goes_to_floor(tmp_path: Path) -> None:
    result = _run_r1(tmp_path, _EnospcStream)
    assert _delta(result, "errors_to_floor") == 1
    assert (tmp_path / "errors_floor.jsonl").exists()


def test_enospc_no_stdlib_logging_error_on_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _run_r1(tmp_path, _EnospcStream)
    assert "Logging error" not in capsys.readouterr().err


# ---------------------------------------------------------------------------
# RED 5-6: ошибка не липнет
# ---------------------------------------------------------------------------


def test_error_then_success_not_refused(tmp_path: Path) -> None:
    def _scenario() -> dict[str, Any]:
        lm = LoggerManager(config={"log_directory": str(tmp_path)})
        try:
            for ch in lm.get_all_channels():
                _swap_stream(ch.handler, _FlakyStream(fail_times=1))
            s0 = lm.get_stats()
            lm.warning("first", module="probe")
            s1 = lm.get_stats()
            lm.warning("second", module="probe")
            s2 = lm.get_stats()
            return {"s0": s0, "s1": s1, "s2": s2}
        finally:
            lm.shutdown()

    r = _bounded(_scenario)
    # warning идёт в два канала (console, system_file): оба хэндлера падают один раз
    assert r["s1"]["channel_refused_records"] - r["s0"]["channel_refused_records"] == 2
    # вторая запись: потоки здоровы, ошибка первой не переходит на неё
    assert r["s2"]["channel_written_records"] - r["s1"]["channel_written_records"] == 2
    assert r["s2"]["channel_refused_records"] - r["s1"]["channel_refused_records"] == 0


def test_shared_handler_second_channel_does_not_inherit_error(tmp_path: Path) -> None:
    path = str(tmp_path / "shared.log")
    ch_a = FileChannel(LoggerChannelSchema(name="chan_a", type="file", file_path=path))
    ch_b = FileChannel(LoggerChannelSchema(name="chan_b", type="file", file_path=path))
    try:
        assert ch_a.handler is ch_b.handler, "каналы одного файла обязаны делить хэндлер"
        _swap_stream(ch_a.handler, _FlakyStream(fail_times=1))
        first = _bounded(lambda: ch_a.write(_record("one")))
        second = _bounded(lambda: ch_b.write(_record("two")))
        assert first == {"status": "error", "channel": "chan_a", "error": _ENOSPC_TEXT}
        assert second == {"status": "success", "channel": "chan_b"}
    finally:
        ch_a.close()
        ch_b.close()


# ---------------------------------------------------------------------------
# RED 7-8: консоль, rotate: false, форма ответа
# ---------------------------------------------------------------------------


def test_console_channel_enospc_gives_error() -> None:
    ch = ConsoleChannel(LoggerChannelSchema(name="console", type="console"))
    ch.handler.stream = _EnospcStream()
    result = _bounded(lambda: ch.write(_record()))
    assert result == {"status": "error", "channel": "console", "error": _ENOSPC_TEXT}


def test_rotate_false_channel_enospc_gives_error(tmp_path: Path) -> None:
    ch = FileChannel(
        LoggerChannelSchema(name="plain_file", type="file", rotate=False, file_path=str(tmp_path / "plain.log"))
    )
    try:
        _swap_stream(ch.handler, _EnospcStream())
        result = _bounded(lambda: ch.write(_record()))
        assert result == {"status": "error", "channel": "plain_file", "error": _ENOSPC_TEXT}
    finally:
        ch.close()


def test_error_response_shape(tmp_path: Path) -> None:
    ch = FileChannel(LoggerChannelSchema(name="system_file", type="file", file_path=str(tmp_path / "system.log")))
    try:
        _swap_stream(ch.handler, _EnospcStream())
        result = _bounded(lambda: ch.write(_record("secret-payload-xyz")))
        assert result == {"status": "error", "channel": "system_file", "error": _ENOSPC_TEXT}
        assert "secret-payload-xyz" not in result["error"]
    finally:
        ch.close()


# ---------------------------------------------------------------------------
# Правки по ревью стадии 5: входное значение не утекает в ответ; hazard общего хэндлера
# ---------------------------------------------------------------------------


def _write_through_failing_stream(tmp_path: Path, exc: BaseException) -> dict[str, Any]:
    ch = FileChannel(LoggerChannelSchema(name="leak_probe", type="file", file_path=str(tmp_path / "leak.log")))
    try:
        _swap_stream(ch.handler, _RaisingStream(exc))
        return _bounded(lambda: ch.write(_record("payload-text")))
    finally:
        ch.close()


def test_non_oserror_gives_class_name_only(tmp_path: Path) -> None:
    # Настоящая защита от утечки входного значения (проверка в test_error_response_shape
    # на OSError(28) вакуумна: текст ОС там и так не секрет).
    result = _write_through_failing_stream(tmp_path, ValueError("secret-payload-xyz"))
    assert result == {"status": "error", "channel": "leak_probe", "error": "ValueError"}
    assert "secret-payload-xyz" not in result["error"]


def test_oserror_without_errno_gives_class_name_only(tmp_path: Path) -> None:
    result = _write_through_failing_stream(tmp_path, OSError("secret-payload-xyz"))
    assert result == {"status": "error", "channel": "leak_probe", "error": "OSError"}
    assert "secret-payload-xyz" not in result["error"]


def test_oserror_without_strerror_omits_none(tmp_path: Path) -> None:
    result = _write_through_failing_stream(tmp_path, OSError(28, None))
    assert result == {"status": "error", "channel": "leak_probe", "error": "OSError: errno 28"}


def test_handle_error_outside_except_gives_unknown_error(tmp_path: Path) -> None:
    ch = FileChannel(LoggerChannelSchema(name="outside", type="file", file_path=str(tmp_path / "outside.log")))
    try:
        record = logging.LogRecord("probe", logging.WARNING, "", 0, "m", (), None)
        ch.handler.handleError(record)
        assert ch.handler._last_error == "UnknownError"
    finally:
        ch.close()


def test_shared_handler_two_threads_no_false_error(tmp_path: Path) -> None:
    """Два потока на общий хэндлер: канал A всегда падает, канал B всегда здоров.

    Серийность записи даёт общий ``sink_lock`` (``_bind_sink_lock``); без него
    ``_last_error`` одного канала читает другой и B отвечает ложным ``error``.
    """
    path = str(tmp_path / "hazard.log")
    # дедлайн ожидания лока с запасом: тест проверяет ложные error, а не потерю по пределу
    cfg = {"type": "file", "file_path": path, "write_deadline_sec": 5.0}
    ch_a = FileChannel(LoggerChannelSchema(name="chan_a", **cfg))
    ch_b = FileChannel(LoggerChannelSchema(name="chan_b", **cfg))
    counts = {"a_success": 0, "b_error": 0}
    old_interval = sys.getswitchinterval()
    try:
        assert ch_a.handler is ch_b.handler, "каналы одного файла обязаны делить хэндлер"
        _swap_stream(ch_a.handler, _SelectiveStream())

        def _run_a() -> None:
            for _ in range(_HAZARD_WRITES):
                if ch_a.write(_record("BADREC"))["status"] == "success":
                    counts["a_success"] += 1

        def _run_b() -> None:
            for _ in range(_HAZARD_WRITES):
                if ch_b.write(_record("good"))["status"] == "error":
                    counts["b_error"] += 1

        sys.setswitchinterval(1e-6)  # частые переключения потоков: гонка проявляется чаще
        threads = [threading.Thread(target=_run_a, daemon=True), threading.Thread(target=_run_b, daemon=True)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(_HAZARD_JOIN_DEADLINE_S)
        assert not any(t.is_alive() for t in threads), "потоки не завершились за дедлайн"
        assert counts == {"a_success": 0, "b_error": 0}
    finally:
        sys.setswitchinterval(old_interval)
        ch_a.close()
        ch_b.close()
