# -*- coding: utf-8 -*-
"""
Регресс R1/R3 (2026-07-10): ошибка через logger-слот hub-wired процесса — ровно
одна запись в сторе и один live-push; error-severity идёт write-through (crash-путь).

Слепая зона до фикса (test_observability_store_wiring.py:85-97 — INFO + adapter=None
+ мок-LoggerCore со словарём `_taps`): петля drain↔tap на РЕАЛЬНОМ
``LoggerCore._emit_to_taps`` + severity=ERROR + реальном ``ObservabilityDrainAdapter``
не покрывалась. Эти тесты гоняют полный контур (worker-слот → hub → drain →
adapter → реальный logger → tap'ы стора и форварда).
"""

from __future__ import annotations

from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

from ...worker_module.core.worker_manager import WorkerManager
from ..managers.observability_wiring import (
    drain_process_observability,
    wire_observability_forward,
    wire_observability_store,
    wire_process_observability,
)


class _CollectSink:
    """Tap-sink (IChannel): собирает полученные LogRecord-dict."""

    def __init__(self, name: str = "collect") -> None:
        self._name = name
        self.records: list = []

    @property
    def name(self) -> str:
        return self._name

    def write(self, data: dict) -> dict:
        self.records.append(data)
        return {"status": "success", "channel": self._name}

    def close(self) -> None:
        pass


class _FakeRouter:
    """Роутер-заглушка: считает адресные пуши форвардера."""

    def __init__(self) -> None:
        self.sent: list = []

    def send_async(self, message: dict, priority: str = "normal") -> None:
        self.sent.append((message, priority))


def _real_logger(name: str) -> LoggerManager:
    mgr = LoggerManager(manager_name=name)
    mgr.initialize()
    return mgr


# ---------------------------------------------------------------------------
# Обязательный тест №1 — интеграционный регресс петли drain↔tap
# ---------------------------------------------------------------------------


def test_error_via_logger_slot_single_store_row_and_single_forward(tmp_path):
    """1 эмиссия ERROR через logger-слот hub-wired процесса → РОВНО одна строка в
    сторе и РОВНО один live-push. Кусается на старом коде: там error задваивался
    (kind='log' из drain-петли + kind='error' из tap) и пушился дважды."""
    logger = _real_logger("wt-logger")
    error_mgr = _real_logger("wt-error")
    worker = WorkerManager("workers")

    hub, adapter = wire_process_observability("cam0", worker, logger, None, error_mgr)
    store, _store_taps = wire_observability_store(error_mgr, logger, db_path=str(tmp_path / "obs.db"), process="cam0")
    router = _FakeRouter()
    forwarder, _fwd_taps = wire_observability_forward(
        router, "gui", "cam0", logger_manager=logger, error_manager=error_mgr
    )

    # Эмиссия ошибки через logger-слот (как worker-пилот: _log_error → слот 'logger').
    worker._log_error("boom", module="cam0")

    # Дренаж такта heartbeat: sink-менеджеры + стор + форвардер.
    drain_process_observability(hub, adapter, store, forwarder)

    # РОВНО одна запись в сторе — и это error, не задвоенный log.
    assert store.count() == 1
    assert store.count(kind="error") == 1
    assert store.count(kind="log") == 0
    rows = store.list_records(kind="error")
    assert rows[0]["message"] == "boom"

    # РОВНО один live-push (write-through tap), без второго из drain-пачки.
    assert len(router.sent) == 1

    store.close()


# ---------------------------------------------------------------------------
# Обязательный тест №2 — crash-путь R3: write-through ДО drain
# ---------------------------------------------------------------------------


def test_error_via_logger_slot_write_through_before_drain(tmp_path):
    """R3: ошибка через logger-слот достигает sink/tap ДО всякого drain
    (write-through), в hub-буфере её нет — при SIGKILL не теряется."""
    logger = _real_logger("wt-logger-2")
    worker = WorkerManager("workers")
    hub, _adapter = wire_process_observability("cam0", worker, logger, None, None)

    sink = _CollectSink()
    logger.add_tap(sink, min_level="ERROR")

    worker._log_error("crash", module="cam0")

    # Tap поймал запись НЕМЕДЛЕННО, до любого drain.
    assert len(sink.records) == 1
    assert sink.records[0]["message"] == "crash"
    assert sink.records[0]["level"] == "ERROR"

    # hub log-буфер ошибку НЕ содержит (мимо буфера) → drain её не переиграет.
    drained = hub.drain_all()
    assert drained["log"] == []
    assert drained["error"] == []


def test_critical_via_logger_slot_write_through_before_drain(tmp_path):
    """severity=critical через logger-слот тоже write-through (не в hub-буфер)."""
    logger = _real_logger("wt-logger-3")
    worker = WorkerManager("workers")
    hub, _adapter = wire_process_observability("cam0", worker, logger, None, None)

    sink = _CollectSink()
    logger.add_tap(sink, min_level="ERROR")

    worker._log_critical("fatal", module="cam0")

    assert len(sink.records) == 1
    assert sink.records[0]["level"] == "CRITICAL"
    assert hub.drain_all()["log"] == []


# ---------------------------------------------------------------------------
# Не-регресс: info/warning остаются буфер+drain (min ERROR tap их не ловит)
# ---------------------------------------------------------------------------


def test_info_via_logger_slot_is_write_through_too(tmp_path):
    """severity < ERROR тоже write-through (2.2): hub-буфера для лога больше нет.

    Инверсия прежнего теста. До 2026-07-28 здесь утверждалось обратное — info
    буферизовалась в hub и доезжала до писателя только по такту heartbeat. Буфер
    снят вместе с расщепителем: у лога один путь на все severity.
    """
    logger = _real_logger("wt-logger-4")
    worker = WorkerManager("workers")
    hub, _adapter = wire_process_observability("cam0", worker, logger, None, None)

    error_only = _CollectSink("error_only")
    logger.add_tap(error_only, min_level="ERROR")

    worker._log_info("hello", module="cam0")

    # tap с порогом ERROR по-прежнему молчит — но уже потому, что порог, а не буфер.
    assert error_only.records == []
    # В hub-буфере записи нет ни на одной severity.
    assert hub.drain_all()["log"] == []


def test_sub_error_log_reaches_a_log_tail_subscriber_live(tmp_path):
    """Живой хвост sub-ERROR логов НЕ потерян со снятием hub-форварда.

    Снимая лог-буфер, мы убрали и пачку `drained[KIND_LOG]`, которой раньше жил
    live-хвост подписчиков. Утверждение «замена уже есть» проверяется здесь, а не
    объявляется: `log.tail.subscribe` вешает tap прямо на `logger_manager` с уровнем
    подписчика (`log_tail::{subscriber}`, Ф1.5). Раз запись доезжает до писателя
    немедленно, tap видит её живьём — и видит РАНЬШЕ, чем раньше видел drain.
    """
    logger = _real_logger("wt-logger-5")
    worker = WorkerManager("workers")
    hub, _adapter = wire_process_observability("cam0", worker, logger, None, None)

    tail = _CollectSink("log_tail::gui")
    logger.add_tap(tail, min_level="INFO", name="log_tail::gui")

    worker._log_info("кадр обработан", module="cam0")

    assert [r["message"] for r in tail.records] == ["кадр обработан"]
    assert hub.drain_all()["log"] == []  # и ровно один раз, не считая буфера
