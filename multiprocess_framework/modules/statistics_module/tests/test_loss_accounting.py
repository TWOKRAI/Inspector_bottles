# -*- coding: utf-8 -*-
"""P5 — инвариант «невидимый дроп невозможен» для ТРЕТЬЕЙ плоскости.

Резидуал P5 ревью фазы Ф0: учёт потерь (Ф0.4) остался в ``LoggerCore``, а не в
общей базе. У логов и ошибок потеря названа и видна наружу, у статистики —
``StatsManager._do_flush`` ловил только исключение и увеличивал безымянный
``_errors``; отказ канала СТАТУСОМ (``{"status": "error"}``) не считался вовсе.
Инвариант 2 плана работал для двух плоскостей из трёх.

Характеризация снята ДО подъёма учёта в базу. Тесты, помеченные как намеренное
изменение, красные на старом коде — это объявлено, а не обнаружено потом.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ...channel_routing_module.interfaces import IChannel
from ..core.stats_manager import StatsManager


class _SpyChannel(IChannel):
    def __init__(self, name: str, *, mode: str = "ok") -> None:
        self._name = name
        self.mode = mode
        self.written: List[Dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return "spy"

    def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if self.mode == "raise":
            raise RuntimeError("канал статистики сломан")
        if self.mode == "refuse":
            return {"status": "error", "channel": self._name}
        self.written.append(data)
        return {"status": "success", "channel": self._name}

    def close(self) -> None:
        pass


def _manager(mode: str = "ok") -> tuple[StatsManager, _SpyChannel]:
    """Менеджер статистики с ОДНИМ подконтрольным каналом."""
    sm = StatsManager(manager_name="LossStats", config={"enable_logging": False, "channels": {}})
    sm.initialize()
    for name in list(sm._channel_registry.names()):
        sm._channel_registry.unregister(name)
    spy = _SpyChannel("spy", mode=mode)
    sm._channel_registry.register(spy)
    return sm, spy


def test_healthy_channel_receives_snapshot() -> None:
    """Предусловие всех проверок ниже: здоровый канал действительно получает снапшот."""
    sm, spy = _manager()
    try:
        sm.increment("проба")
        sm.flush()

        assert spy.written, "снапшот не доехал до канала — сценарий не воспроизведён"
    finally:
        sm.shutdown()


def test_refused_channel_is_counted() -> None:
    """НАМЕРЕННОЕ ИЗМЕНЕНИЕ: отказ канала статусом теперь считается.

    Раньше ``_do_flush`` разбирал только исключение: канал, ответивший
    ``{"status": "error"}``, считался принявшим. Снапшот метрик исчезал молча,
    и спросить об этом живой процесс было нечем.
    """
    sm, _ = _manager(mode="refuse")
    try:
        sm.increment("проба")
        sm.flush()

        assert sm.stats["channel_refused_records"] >= 1, "отказ канала статистики не учтён"
        assert sm.get_stats()["channel_refused_by_channel"].get("spy", 0) >= 1, "нет разбивки по каналу"
    finally:
        sm.shutdown()


def test_raising_channel_is_counted_by_name() -> None:
    """НАМЕРЕННОЕ ИЗМЕНЕНИЕ: исключение канала считается ПОИМЁННО.

    Раньше рос безымянный ``_errors``: «где-то что-то упало». Имя канала-виновника
    и есть то, ради чего счётчик заводят.
    """
    sm, _ = _manager(mode="raise")
    try:
        sm.increment("проба")
        sm.flush()

        assert sm.stats["channel_write_errors"] >= 1
        assert sm.get_stats()["channel_write_errors_by_channel"].get("spy", 0) >= 1
    finally:
        sm.shutdown()


def test_counters_present_as_zero_when_healthy() -> None:
    """Ключи есть ВСЕГДА: «ключа нет» и «потерь нет» — разные факты.

    Та же дисциплина, что у логгера (Ф0.4). Потребитель
    ``introspect.observability`` не должен различать плоскости по наличию ключа.
    """
    sm, _ = _manager()
    try:
        sm.increment("проба")
        sm.flush()

        published = sm.get_stats()
        for key in (
            "unresolved_channel_records",
            "channel_write_errors",
            "channel_refused_records",
            "records_without_channels",
        ):
            assert published[key] == 0, f"{key} ненулевой на здоровой плоскости"
    finally:
        sm.shutdown()


def test_window_book_counts_what_the_sink_accepted() -> None:
    """Книга окна агрегации считает ПРИНЯТОЕ, а не отданное.

    До P5 ``AggregationWindow`` вообще не смотрело на результат ``flush_fn``:
    сток мог не принять ни одной записи, а по книгам окна всё выглядело
    сброшенным. Тот же класс, что стрелял в Ф0.3 у ``BatchBuffer``, где
    ``total_flushed`` означал «отдано».
    """
    sm, _ = _manager(mode="refuse")
    try:
        sm.increment("проба")
        sm.flush()

        book = sm.get_stats()["buffer"]
        assert book["flush_failed"] >= 1, "непринятое не попало в книгу окна"
        assert book["total_flushed"] == 0, "непринятое посчитано как записанное"
    finally:
        sm.shutdown()


def test_window_book_counts_success() -> None:
    """Парная половина: на здоровом стоке книга не должна показывать потери."""
    sm, _ = _manager()
    try:
        sm.increment("проба")
        sm.flush()

        book = sm.get_stats()["buffer"]
        assert book["total_flushed"] >= 1
        assert book["flush_failed"] == 0
    finally:
        sm.shutdown()
