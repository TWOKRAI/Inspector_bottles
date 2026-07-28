# -*- coding: utf-8 -*-
"""
Тесты wiring'а ObservabilityHub в composition root процесса (Ф5.16 → 2.2).

Контракт (решение владельца 2026-07-09 §6.1, упрощён 2026-07-28):
  - hub — один на процесс, тег = имя процесса;
  - пилот — worker_module (пустой реестр слотов → безопасная подмена);
  - stats worker'а → hub (буфер, drain по такту heartbeat);
  - **logger-слот worker'а → РЕАЛЬНЫЙ logger_manager, на всех severity.**
    До 2.2 здесь стоял `_LoggerSlotSplitter`: error/critical write-through, ниже —
    в hub-буфер. Расщепитель был лекарством от двух дефектов буферизации лога
    (R1 — дубль через переигрывание drain'ом, R3 — потеря буфера при SIGKILL).
    Снят вместе с причиной: без лог-буфера переигрывать и терять нечего;
  - error-слот worker'а → реальный error_manager (write-through, переживает
    SIGKILL: инвариант 3, буфер не полагается на finally/atexit).

Инвариант в его окончательном виде: **лог не попадает в hub-буфер НИКОГДА** —
это структурное свойство, а не соглашение о том, какие severity write-through.
"""

from ...channel_routing_module.observability import KIND_LOG
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


def test_wire_injects_hub_into_stats_and_real_logger_into_logger_slot():
    """stats-слот — чистый hub; logger-слот — САМ реальный менеджер, без прослойки."""
    worker, logger, _, _, hub, _ = _wire()
    assert worker.get_manager("stats") is hub
    assert worker.get_manager("logger") is logger
    assert worker.get_manager("logger") is not hub


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


def test_logger_slot_falls_back_to_hub_when_no_logger():
    """Вырожденный случай: логгера нет → слотом остаётся hub.

    Свойство «терять можно, молчать нельзя»: без этой ветки слот получил бы None и
    записи воркера исчезли бы бесследно, вместо того чтобы копиться в bounded-канале
    со счётчиком потерь.
    """
    worker = WorkerManager("workers")
    hub, _ = wire_process_observability("proc", worker, None, None, None)
    assert worker.get_manager("logger") is hub

    worker._log_info("некуда писать", module="w")
    assert len(hub.get_channel(KIND_LOG).drain()) == 1


# ---------------------------------------------------------------------------
# Лог мимо буфера — структурное свойство (снятие R1/R3 по построению)
# ---------------------------------------------------------------------------


def test_worker_log_reaches_real_logger_without_any_drain():
    """Лог воркера у писателя СРАЗУ, до всякого drain — и в буфере его нет.

    Раньше эта запись жила в hub'е до такта heartbeat: при SIGKILL (auto-restart
    Ф3.7 бьёт именно им) она пропадала вместе с буфером — это и есть R3.
    """
    worker, logger, _, _, hub, _ = _wire()

    worker._log_info("hello", module="w")

    assert any(c[0] == "info" and c[1][0] == "hello" for c in logger.calls)
    assert hub.drain_all()[KIND_LOG] == []


def test_no_severity_of_log_ever_enters_the_hub_buffer():
    """НИ ОДНА severity лога не попадает в hub-буфер.

    Именно эта строчка отличает новый контракт от старого: прежний инвариант был
    пер-severity («ниже ERROR — в буфер, выше — write-through»), и его приходилось
    держать в голове в трёх местах. Теперь буфера для лога нет вовсе.
    """
    worker, _, _, _, hub, _ = _wire()

    for emit, text in (
        (worker._log_debug, "d"),
        (worker._log_info, "i"),
        (worker._log_warning, "w"),
        (worker._log_error, "e"),
        (worker._log_critical, "c"),
    ):
        emit(text, module="w")

    assert hub.drain_all()[KIND_LOG] == []


def test_drain_does_not_replay_log_into_the_writer():
    """R1 по построению: drain после эмиссии НЕ добавляет второй записи.

    Прежний дефект: drain отдавал лог-запись адаптеру, тот переигрывал её в
    logger_manager, где tap (min ERROR) писал ВТОРУЮ запись kind='error' — дубль в
    сторе и в обеих вкладках GUI. Переигрывать больше нечего.
    """
    worker, logger, _, _, hub, adapter = _wire()

    worker._log_error("e", module="w")
    calls_before = len(logger.calls)

    drain_process_observability(hub, adapter)

    assert len(logger.calls) == calls_before


def test_worker_stat_buffered_then_drained():
    """stats-слот остаётся буферизуемым — снятие лог-буфера его не касается."""
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
# Контракт-тест: буферизуется РОВНО одна плоскость из трёх
# ---------------------------------------------------------------------------


def test_only_stats_is_buffered():
    """Контракт Ф5.16 в редакции 2.2: из трёх плоскостей буфер остался у ОДНОЙ.

    Исходная формулировка «слот → ЛИБО sink, ЛИБО hub» огрублялась дважды: сначала
    её пришлось уточнить до пер-severity (R1 — дубль от петли drain↔tap), теперь она
    вернулась к простому виду, потому что у лога буфера нет. Проверяем поведенчески:
    лог и ошибка доезжают до своих менеджеров без drain, метрика — только после.
    """
    worker, logger, stats, error, hub, adapter = _wire()

    assert worker.get_manager("logger") is logger
    assert worker.get_manager("error") is error
    assert worker.get_manager("stats") is hub

    worker._log_info("i", module="w")
    worker._track_error(ValueError("e"))
    worker._record_metric("m", 1)

    # Лог и ошибка — у своих менеджеров немедленно.
    assert any(c[0] == "info" for c in logger.calls)
    assert error.calls
    # Метрика — ещё в буфере, менеджер не тронут.
    assert stats.calls == []

    drain_process_observability(hub, adapter)
    assert any(c[1] and c[1][0] == "m" for c in stats.calls)
