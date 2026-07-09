# -*- coding: utf-8 -*-
"""
Тесты wiring'а ObservabilityHub в composition root процесса (Ф5.16).

Контракт (решение владельца 2026-07-09 §6.1):
  - hub — один на процесс, тег = имя процесса;
  - пилот — worker_module (пустой реестр слотов → безопасная подмена);
  - log/stats worker'а → hub (буфер, drain по heartbeat);
  - error-слот worker'а → реальный error_manager (write-through, переживает
    SIGKILL: инвариант 3, буфер не полагается на finally/atexit);
  - контракт «слот менеджера → ЛИБО sink, ЛИБО hub, не оба».
"""

from ...worker_module.core.worker_manager import WorkerManager
from ..managers.observability_wiring import (
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


def test_wire_injects_hub_into_log_and_stats_slots():
    worker, _, _, _, hub, _ = _wire()
    assert worker.get_manager("logger") is hub
    assert worker.get_manager("stats") is hub


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
# Контракт: каждый слот → ЛИБО sink, ЛИБО hub, не оба
# ---------------------------------------------------------------------------


def test_slot_is_either_sink_or_hub_not_both():
    """Плановый контракт-тест Ф5.16: буферизуемые слоты (logger/stats) — это hub;
    write-through слот (error) — реальный sink; пересечения нет."""
    worker, logger, stats, error, hub, _ = _wire()

    slots = {name: worker.get_manager(name) for name in ("logger", "stats", "error")}

    # log/stats — строго hub (буфер), error — строго реальный sink (write-through).
    assert slots["logger"] is hub and slots["stats"] is hub
    assert slots["error"] is error
    # Ни один слот не указывает одновременно и на hub, и на реальный sink.
    assert slots["error"] is not hub
    assert slots["logger"] is not logger and slots["stats"] is not stats
