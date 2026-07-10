# -*- coding: utf-8 -*-
"""
Тесты wiring'а ObservabilityHub в composition root процесса (Ф5.16).

Контракт (решение владельца 2026-07-09 §6.1):
  - hub — один на процесс, тег = имя процесса;
  - пилот — worker_module (пустой реестр слотов → безопасная подмена);
  - stats worker'а → hub (буфер, drain по heartbeat);
  - logger-слот worker'а → _LoggerSlotSplitter (уточнение R1/R3 2026-07-10):
    info/warning/debug → hub-буфер; error/critical → write-through в реальный
    logger_manager (иначе петля drain↔tap задваивала ошибку — R1);
  - error-слот worker'а → реальный error_manager (write-through, переживает
    SIGKILL: инвариант 3, буфер не полагается на finally/atexit);
  - контракт «слот менеджера → ЛИБО sink, ЛИБО hub, не оба» уточнён до
    пер-severity: КАЖДАЯ severity уходит РОВНО в один приёмник (sink XOR буфер).
"""

from ...worker_module.core.worker_manager import WorkerManager
from ..managers.observability_wiring import (
    _LoggerSlotSplitter,
    drain_process_observability,
    wire_process_observability,
)


class RecordingSink:
    """Мок-sink: перехватывает любой вызов метода в self.calls."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def _rec(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return True  # гасим fallback track_error→record_error в _track_error

        return _rec


def _wire():
    worker = WorkerManager("workers")
    logger, stats, error = RecordingSink(), RecordingSink(), RecordingSink()
    hub, adapter = wire_process_observability("proc", worker, logger, stats, error)
    return worker, logger, stats, error, hub, adapter


# ---------------------------------------------------------------------------
# Инъекция в слоты
# ---------------------------------------------------------------------------


def test_wire_injects_hub_into_stats_and_splitter_into_logger():
    """stats-слот — чистый hub; logger-слот — расщепитель поверх того же hub'а
    (R1/R3: info/warning/debug буферизуются в hub, error/critical — write-through)."""
    worker, _, _, _, hub, _ = _wire()
    assert worker.get_manager("stats") is hub
    logger_slot = worker.get_manager("logger")
    assert isinstance(logger_slot, _LoggerSlotSplitter)
    # Не-error эмиссия оседает в буфере того же hub'а (буферизуемый путь сохранён).
    worker._log_info("hi", module="w")
    assert len(hub.get_channel("log").drain()) == 1


def test_wire_keeps_error_slot_write_through():
    """Контракт: error-слот — реальный менеджер, НЕ hub (write-through)."""
    worker, _, _, error, hub, _ = _wire()
    assert worker.get_manager("error") is error
    assert worker.get_manager("error") is not hub


def test_wire_none_worker_returns_none():
    hub, adapter = wire_process_observability("proc", None, None, None, None)
    assert hub is None and adapter is None


def test_hub_tagged_with_process_name():
    _, _, _, _, hub, _ = _wire()
    assert hub.module_name == "proc"


# ---------------------------------------------------------------------------
# Буферизуемый путь log/stats + паритет через drain
# ---------------------------------------------------------------------------


def test_worker_log_buffered_then_drained_to_real_logger():
    worker, logger, _, _, hub, adapter = _wire()

    worker._log_info("hello", module="w")
    # До drain реальный logger НЕ тронут — запись в буфере hub'а.
    assert logger.calls == []

    drain_process_observability(hub, adapter)
    assert any(c[0] == "info" and c[1][0] == "hello" for c in logger.calls)


def test_worker_stat_buffered_then_drained():
    worker, _, stats, _, hub, adapter = _wire()
    worker._record_metric("hits", 5)
    assert stats.calls == []
    drain_process_observability(hub, adapter)
    # hub.record_metric помечает запись METRIC_GAUGE → адаптер → stats.gauge;
    # тест буфера/дренажа проверяет приход метрики по имени, не тип-роутинг.
    assert any(c[1] and c[1][0] == "hits" for c in stats.calls)


# ---------------------------------------------------------------------------
# Write-through error (crash-путь)
# ---------------------------------------------------------------------------


def test_worker_error_write_through_immediately():
    """error/critical идут в реальный менеджер СРАЗУ (до любого drain) —
    иначе SIGKILL (auto-restart 3.7) потерял бы буфер."""
    worker, _, _, error, hub, _ = _wire()
    exc = ValueError("boom")
    worker._track_error(exc)

    # Реальный error-менеджер получил ошибку немедленно, без drain.
    assert any(exc in c[1] for c in error.calls)
    # hub error-канал пуст — ошибка мимо буфера.
    assert len(hub.drain_all()["error"]) == 0


def test_worker_critical_error_write_through():
    """severity=critical также идёт write-through (не в буфер hub'а)."""
    worker, _, _, error, hub, _ = _wire()
    worker._track_error(RuntimeError("fatal"), {"severity": "critical"})
    assert error.calls  # доставлено немедленно
    assert len(hub.drain_all()["error"]) == 0


# ---------------------------------------------------------------------------
# Контракт: КАЖДАЯ severity → ЛИБО sink, ЛИБО hub, не оба (уточнён пер-severity)
# ---------------------------------------------------------------------------


def test_each_severity_routed_to_exactly_one_receiver():
    """Контракт-тест Ф5.16, уточнён R1/R3 (2026-07-10): исходный инвариант «слот →
    ЛИБО sink, ЛИБО hub» огрублял logger-слот (одна ошибка задваивалась петлёй
    drain↔tap — R1). Точный инвариант — пер-severity: КАЖДАЯ эмиссия уходит РОВНО
    в один приёмник (реальный sink XOR hub-буфер), пересечения нет.

    - stats-слот — чистый hub (буфер);
    - error-слот (track_error) — реальный error_manager (write-through);
    - logger-слот — расщепитель: severity<ERROR → hub-буфер, ≥ERROR → реальный
      logger (write-through). Проверяем ПОВЕДЕНЧЕСКИ обе ветки на непересечение.
    """
    worker, logger, stats, error, hub, _ = _wire()

    # stats — строго hub; error-слот — строго реальный sink (не hub).
    assert worker.get_manager("stats") is hub
    assert worker.get_manager("error") is error
    assert worker.get_manager("error") is not hub

    # logger-слот — расщепитель, не сам hub и не сам реальный logger.
    logger_slot = worker.get_manager("logger")
    assert isinstance(logger_slot, _LoggerSlotSplitter)
    assert logger_slot is not hub and logger_slot is not logger

    # severity < ERROR → РОВНО в hub-буфер, реальный logger НЕ тронут.
    worker._log_info("i", module="w")
    assert logger.calls == []
    assert len(hub.get_channel("log").drain()) == 1

    # severity ≥ ERROR → РОВНО в реальный logger (write-through), hub-буфер пуст.
    worker._log_error("e", module="w")
    assert any(c[0] == "error" and c[1][0] == "e" for c in logger.calls)
    assert len(hub.get_channel("log").drain()) == 0
