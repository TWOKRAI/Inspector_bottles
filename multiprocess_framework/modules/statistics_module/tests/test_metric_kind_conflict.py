# -*- coding: utf-8 -*-
"""
Задача 0.11b (M-4, минимум): запись метрики ДРУГОГО вида под существующим
ключом не пропадает молча.

ПЕРЕХОДНЫЙ файл: после задачи 1.2 вид входит в ключ серии, серии разных видов
раздельны и ``metric_kind_conflicts == 0`` у пары counter/timing — 1.2
переписывает этот файл.

Ключ серии (имя + теги) не менялся. «Вид» — ``MetricType`` записи. Запись другого
вида под занятым ключом отвергается: первая серия нетронута, счётчик
``metric_kind_conflicts`` растёт на КАЖДЫЙ конфликт, голос (WARNING) звучит не
чаще окна на ключ и только после выхода из ``_metrics_lock``.

Логгер подаётся через ``managers={"logger": MagicMock()}``: без слота ``logger``
``log_windowed`` молчит, а ``caplog`` не годится — порт пишет через
``get_std_logger``.
"""

import sys
import threading
from unittest.mock import MagicMock

from .. import StatsManager
from ...channel_routing_module.interfaces import IChannel

#: Дедлайн hazard-тестов: поток, не успевший за него, считается зависшим.
_JOIN_DEADLINE_S = 5.0


class _CapturingChannel(IChannel):
    """Канал-шпион: копит снапшоты окна такими, какими их видит канал."""

    def __init__(self, name: str = "capture"):
        self._name = name
        self.received = []

    @property
    def name(self):
        return self._name

    def write(self, data):
        self.received.append(data)
        return {"status": "ok"}

    def close(self):
        pass


def _make_manager(logger=None, name: str = "KindConflictTest", cls=StatsManager) -> "tuple[StatsManager, MagicMock]":
    """Менеджер с mock-логгером в слоте 'logger'.

    ``aggregation_interval == flush_interval``, чтобы посторонний WARNING про
    «пол темпа» не засорял список вызовов логгера.
    """
    mock_logger = logger if logger is not None else MagicMock()
    mgr = cls(
        manager_name=name,
        config={
            "enable_logging": False,
            "channels": {},
            "aggregation_interval": 1.0,
            "flush_interval": 1.0,
        },
        managers={"logger": mock_logger},
    )
    assert mgr.initialize() is True, "менеджер не инициализировался — сценарий недостоверен"
    return mgr, mock_logger


def _conflicts(mgr: StatsManager):
    return mgr.get_stats().get("metric_kind_conflicts")


def test_timing_under_counter_counted():
    mgr, _ = _make_manager()
    mgr.record_metric("x")
    mgr.record_timing("x", 0.5)
    mgr.record_timing("x", 0.7)
    assert _conflicts(mgr) == 2


def test_counter_under_timing_counted():
    mgr, _ = _make_manager()
    mgr.record_timing("y", 0.5)
    mgr.record_metric("y")
    assert _conflicts(mgr) == 1


def test_one_warning_per_window():
    mgr, logger = _make_manager()
    mgr.record_metric("x")
    mgr.record_metric("y")
    mgr.record_timing("x", 0.5)
    mgr.record_timing("x", 0.7)
    mgr.record_timing("y", 0.5)
    assert logger.warning.call_count == 2


def test_conflict_not_emitted_after_flush():
    mgr, _ = _make_manager()
    # Канал-шпион стоит как tap: tap видит СЫРУЮ эмиссию. Через ``register_channel``
    # конфликтную запись не увидеть — окно агрегации держит вид первой серии и
    # в снапшоте тайминг под ``x`` не показывает (проверено на HEAD).
    spy = _CapturingChannel()
    mgr.add_tap(spy, min_level="DEBUG")
    mgr.record_metric("x")
    mgr.record_timing("x", 0.5)
    mgr.flush()
    emitted = [(r.get("name"), r.get("type")) for r in spy.received]
    assert ("x", "counter") in emitted, f"первая серия не дошла до шпиона — сценарий недостоверен: {emitted}"
    assert ("x", "timing") not in emitted


def test_first_series_kept():
    mgr, _ = _make_manager()
    mgr.record_metric("x")
    mgr.record_timing("x", 0.5)
    assert mgr.get_metric("x") == {"name": "x", "type": "counter", "tags": {}, "count": 1.0}


def test_warning_that_records_metric_does_not_deadlock():
    """Голос идёт через логгер, а логгер пишет метрику: под ``_metrics_lock`` это цикл на себя."""
    holder = {}
    logger = MagicMock()
    logger.warning.side_effect = lambda *a, **k: holder["mgr"].record_metric("other")
    mgr, _ = _make_manager(logger=logger)
    holder["mgr"] = mgr
    mgr.record_metric("x")

    worker = threading.Thread(target=lambda: mgr.record_timing("x", 0.5), daemon=True)
    worker.start()
    worker.join(_JOIN_DEADLINE_S)

    assert not worker.is_alive(), "запись конфликта повисла: голос звучит под _metrics_lock"
    assert logger.warning.call_count == 1
    assert mgr.get_metric("other") is not None


def test_concurrent_conflicts_counted():
    mgr, _ = _make_manager()
    mgr.record_metric("x")
    threads_n, per_thread = 8, 50

    def hammer():
        for _ in range(per_thread):
            mgr.record_timing("x", 0.1)

    threads = [threading.Thread(target=hammer, daemon=True) for _ in range(threads_n)]
    old_interval = sys.getswitchinterval()
    # Частые переключения потоков. Гонку «счётчик без лока» это на CPython 3.12 НЕ ловит
    # (инструкции чтения-записи атрибута без вызовов между ними не прерываются) —
    # за лок отвечает тест ниже.
    sys.setswitchinterval(1e-6)
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(_JOIN_DEADLINE_S)
    finally:
        sys.setswitchinterval(old_interval)

    assert not any(t.is_alive() for t in threads), "потоки не завершились за дедлайн"
    assert _conflicts(mgr) == 400


class _LockWatchingManager(StatsManager):
    """Пишет в ``unlocked_writes`` каждую запись счётчика конфликтов, сделанную БЕЗ ``_metrics_lock``."""

    def __setattr__(self, name, value):
        if name == "_metric_kind_conflicts" and value and not self._metrics_lock.locked():
            self.__dict__.setdefault("unlocked_writes", []).append(value)
        super().__setattr__(name, value)


def test_conflict_counter_written_under_metrics_lock():
    """Потоковая гонка счётчика на CPython 3.12 не воспроизводится (см. тест выше), поэтому лок проверен прямо."""
    mgr, _ = _make_manager(cls=_LockWatchingManager)
    mgr.record_metric("x")
    mgr.record_timing("x", 0.5)
    assert _conflicts(mgr) == 1
    assert mgr.__dict__.get("unlocked_writes", []) == []
