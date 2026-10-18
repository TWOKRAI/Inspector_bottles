"""Тесты автора T5.6: опасные места журнала обмена — замки, выключенный журнал, сбои форматтера и логгера.

Purpose:
    Дополняют слепую приёмку (``test_t56_exchange_log_acceptance.py``) свойствами потоков и стоимости.
    H1 — замок журнала не держится во время вызова транспорта; H2 — выключенный журнал ничего не вызывает;
    H3 — сбой форматтера не ломает обмен; H4 — логгер вызывается вне замка журнала. Плюс запись о закрытой
    склейке и сбой самого логгера. Фейк транспорта — только здесь.

Public API:
    Только тесты ``test_*``.

Stability: lite

Каждый тест, который может зависнуть, гоняет вызов в daemon-потоке с дедлайном ``join``.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from typing import Any

import pytest

from Services.device_hub.drivers import exchange_log
from Services.device_hub.drivers.exchange_log import ExchangeLog, ExchangeLogTransport

_DEADLINE_S = 10.0
_TLM = 0x1040
_CMD_SEQ = 0x1001
_HB_PC = 0x1020
_LOGGER_PREFIX = "mpf.Services.device_hub.drivers.exchange_log."


class _Fake:
    """Фейк ``RegisterTransport``: чтение нулями; опциональная блокировка чтения на событии."""

    def __init__(self) -> None:
        self.connected = True
        self.read_gate: threading.Event | None = None
        self.read_entered = threading.Event()

    @property
    def is_connected(self) -> bool:
        return self.connected

    def read_registers(self, address: int, count: int = 1) -> list[int]:
        if self.read_gate is not None:
            self.read_entered.set()
            assert self.read_gate.wait(_DEADLINE_S), "фейк не дождался освобождения"
        return [0] * count

    def transaction(self, ops: list[tuple]) -> bool:
        return True

    def connect(self) -> bool:
        return True

    def disconnect(self) -> None:
        self.connected = False


class _CountingClock:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return float(self.calls)


class _Collector(logging.Handler):
    def __init__(self, gate: threading.Event | None = None) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []
        self.gate = gate
        self.entered = threading.Event()

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)
        if self.gate is not None:
            self.entered.set()
            self.gate.wait(_DEADLINE_S)


@pytest.fixture
def hook() -> Iterator[Any]:
    """Подключает обработчик к логгеру журнала устройства; уровень INFO; уборка в конце."""
    attached: list[tuple[logging.Logger, _Collector, int]] = []

    def _attach(device_id: str, handler: _Collector) -> None:
        logger = logging.getLogger(_LOGGER_PREFIX + device_id)
        attached.append((logger, handler, logger.level))
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

    yield _attach
    for logger, handler, level in attached:
        logger.removeHandler(handler)
        logger.setLevel(level)


def _run(fn: Any) -> threading.Thread:
    thread = threading.Thread(target=fn, daemon=True)
    thread.start()
    return thread


def _join(thread: threading.Thread) -> None:
    thread.join(_DEADLINE_S)
    assert not thread.is_alive(), "поток не завершился за дедлайн"


# --------------------------------------------------------------------------------------------------
# H1: замок журнала не держится во время вызова транспорта
# --------------------------------------------------------------------------------------------------


def test_h1_log_lock_not_held_during_transport_call() -> None:
    fake = _Fake()
    fake.read_gate = threading.Event()
    log = ExchangeLog("h1", periodic=True)
    tr = ExchangeLogTransport(fake, log)
    reader = _run(lambda: tr.read_registers(_TLM, 32))
    try:
        assert fake.read_entered.wait(_DEADLINE_S), "чтение не дошло до фейка"
        writer = _run(lambda: tr.transaction([("w", _CMD_SEQ, 1)]))
        _join(writer)  # завершился, пока чтение внутри транспорта
        assert reader.is_alive()
        assert [ln["text"] for ln in log.get()["lines"]] == ["W CMD_SEQ = 1"]
    finally:
        fake.read_gate.set()
        _join(reader)
    assert [ln["text"] for ln in log.get()["lines"]] == ["W CMD_SEQ = 1", "R TLM_PROTO_VER..+32"]


# --------------------------------------------------------------------------------------------------
# H2: выключенный журнал ничего не вызывает
# --------------------------------------------------------------------------------------------------


def test_h2_disabled_log_calls_no_clock_no_formatter_no_logger(monkeypatch: pytest.MonkeyPatch, hook: Any) -> None:
    calls: list[str] = []

    def _spy(name: str, real: Any) -> Any:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            calls.append(name)
            return real(*args, **kwargs)

        return wrapper

    for name in ("_tx_entries", "_read_entries", "_link_entries", "_tx_op_name"):
        monkeypatch.setattr(exchange_log, name, _spy(name, getattr(exchange_log, name)))
    clock = _CountingClock()
    handler = _Collector()
    hook("h2", handler)
    log = ExchangeLog("h2", clock=clock, enabled=False, periodic=True)
    tr = ExchangeLogTransport(_Fake(), log)

    assert tr.read_registers(_TLM, 4) == [0, 0, 0, 0]
    assert tr.transaction([("wm", 0x1001, [5, 16, 0]), ("w", 0x1000, 1)]) is True
    assert tr.connect() is True
    tr.disconnect()

    assert clock.calls == 0
    assert calls == []
    assert handler.records == []
    state = log.get()
    assert (state["lines"], state["counters"], state["last_seq"], state["log_errors"]) == ([], {}, 0, 0)


# --------------------------------------------------------------------------------------------------
# H3: сбой форматтера не ломает обмен
# --------------------------------------------------------------------------------------------------


def test_h3_formatter_failure_keeps_exchange_alive_and_warns_once(monkeypatch: pytest.MonkeyPatch, hook: Any) -> None:
    def _boom(*_args: Any, **_kwargs: Any) -> list:
        raise RuntimeError("форматтер сломан")

    monkeypatch.setattr(exchange_log, "_tx_entries", _boom)
    handler = _Collector()
    hook("h3", handler)
    log = ExchangeLog("h3", periodic=True)
    tr = ExchangeLogTransport(_Fake(), log)

    assert tr.transaction([("w", _CMD_SEQ, 1)]) is True
    assert tr.transaction([("w", _CMD_SEQ, 2)]) is True

    state = log.get()
    assert state["log_errors"] == 2
    assert state["lines"] == []
    assert state["counters"]["write CMD_SEQ"]["count"] == 2  # счётчики считаются и при сбое форматтера
    warnings = [r for r in handler.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "RuntimeError" in warnings[0].getMessage()


# --------------------------------------------------------------------------------------------------
# H4: логгер вызывается вне замка журнала
# --------------------------------------------------------------------------------------------------


def test_h4_logger_is_called_outside_the_log_lock(hook: Any) -> None:
    gate = threading.Event()
    handler = _Collector(gate)
    hook("h4", handler)
    log = ExchangeLog("h4", periodic=False)
    tr = ExchangeLogTransport(_Fake(), log)
    writer = _run(lambda: tr.transaction([("w", _CMD_SEQ, 1)]))  # новая строка -> запись в логгер -> блок в обработчике
    try:
        assert handler.entered.wait(_DEADLINE_S), "запись не дошла до обработчика логгера"
        reader = _run(lambda: tr.read_registers(_TLM, 32))  # periodic=False: строки и записи нет, счётчик есть
        _join(reader)  # завершился, пока обработчик логгера держит писателя
        assert writer.is_alive()
        assert log.get()["counters"]["read TLM_PROTO_VER"]["count"] == 1
        assert len(handler.records) == 1
    finally:
        gate.set()
        _join(writer)


# --------------------------------------------------------------------------------------------------
# Запись о закрытой склейке и сбой логгера
# --------------------------------------------------------------------------------------------------


def test_closed_merge_writes_times_n_record_and_open_tail_does_not(hook: Any) -> None:
    handler = _Collector()
    hook("tail", handler)
    log = ExchangeLog("tail", periodic=True)
    tr = ExchangeLogTransport(_Fake(), log)
    for _ in range(3):
        tr.transaction([("w", _HB_PC, 7)])
    assert [r.getMessage() for r in handler.records] == ["#1 in W HB_PC = 7"]  # хвост ещё открыт
    tr.transaction([("w", _CMD_SEQ, 1)])
    assert [r.getMessage() for r in handler.records] == ["#1 in W HB_PC = 7", "#1 … ×3", "#2 in W CMD_SEQ = 1"]


def test_logger_failure_is_counted_and_does_not_break_exchange() -> None:
    class _BadLogger:
        def info(self, *_a: Any, **_k: Any) -> None:
            raise OSError("диск")

        def warning(self, *_a: Any, **_k: Any) -> None:
            raise OSError("диск")

    log = ExchangeLog("bad")
    log._logger = _BadLogger()  # type: ignore[assignment]
    tr = ExchangeLogTransport(_Fake(), log)
    assert tr.transaction([("w", _CMD_SEQ, 1)]) is True
    state = log.get()
    assert state["log_errors"] >= 1
    assert [ln["text"] for ln in state["lines"]] == ["W CMD_SEQ = 1"]
