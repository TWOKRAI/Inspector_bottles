# -*- coding: utf-8 -*-
"""
Тест Ф0.6 Item 4 (независимый тестировщик, plans/observability-unified-routing.md):
StatsManager не должен считать метрику N раз при N зарегистрированных каналах.

Контракт: каждая метрика попадает в буфер агрегации ОДИН раз (под sentinel-
ключом), flush-колбэк рассылает уже готовый снапшот ВСЕМ зарегистрированным
каналам. Значит счётчик в снапшоте у КАЖДОГО канала — это записанный тотал,
а НЕ тотал, умноженный на количество каналов.

Это РЕГРЕССИОННЫЙ страж: тест обязан быть зелёным ДО и ПОСЛЕ фикса Ф0.6 —
в отличие от остальных пунктов ТЗ, здесь поведение НЕ меняется намеренно,
только защищается от случайной порчи при рефакторинге под симметрию
Logger/Error/Stats (add_tap/set_sink_enabled).
"""

from __future__ import annotations

from multiprocess_framework.modules.channel_routing_module.interfaces import IChannel
from multiprocess_framework.modules.statistics_module.core.stats_manager import StatsManager


class _DummyChannel(IChannel):
    """Канал-шпион: сохраняет всё, что в него записали (IChannel-совместим)."""

    def __init__(self, name: str) -> None:
        self._name = name
        self.received: list = []

    @property
    def name(self) -> str:
        return self._name

    def write(self, data: dict) -> dict:
        self.received.append(data)
        return {"status": "ok"}

    def close(self) -> None:
        pass


class TestNoDoubleCounting:
    """Известный по количество каналов счётчик не должен умножаться на N."""

    def test_counter_snapshot_not_multiplied_by_channel_count(self) -> None:
        mgr = StatsManager(manager_name="NoDoubleCount", config={"enable_logging": False})
        mgr.initialize()
        try:
            channels = [_DummyChannel(f"ch{i}") for i in range(3)]
            for ch in channels:
                mgr.register_channel(ch)

            repeats = 7
            for _ in range(repeats):
                mgr.increment("requests.count")

            mgr.flush()

            for ch in channels:
                assert len(ch.received) >= 1, f"{ch.name} не получил ни одного snapshot'а"
                snapshot = ch.received[0]
                metrics = snapshot.get("metrics", [])
                metric = next((m for m in metrics if m["name"] == "requests.count"), None)
                assert metric is not None, f"{ch.name}: метрика отсутствует в снапшоте"
                assert metric["count"] == float(repeats), (
                    f"{ch.name}: count={metric['count']}, ожидалось {repeats} "
                    f"(НЕ {repeats * len(channels)} — иначе N-кратный подсчёт по числу каналов)"
                )
        finally:
            mgr.shutdown()

    def test_buffer_enqueues_metric_once_regardless_of_channel_count(self) -> None:
        """Прямая проверка буфера агрегации: total_enqueued растёт по числу
        record_metric-вызовов, а НЕ по числу (вызовы × зарегистрированные каналы)."""
        mgr = StatsManager(manager_name="NoDoubleCount2", config={"enable_logging": False})
        mgr.initialize()
        try:
            mgr.register_channel(_DummyChannel("a"))
            mgr.register_channel(_DummyChannel("b"))

            calls = 3
            for _ in range(calls):
                mgr.increment("x")

            stats = mgr.get_stats()
            enqueued = stats["buffer"]["total_enqueued"]
            assert enqueued == calls, (
                f"total_enqueued={enqueued}, ожидалось {calls} (число record_metric-вызовов, "
                f"НЕ умноженное на 2 зарегистрированных канала)"
            )
        finally:
            mgr.shutdown()

    def test_single_channel_and_multi_channel_see_same_count(self) -> None:
        """Оракульная проверка: снапшот у 1-канального и N-канального менеджера
        для ОДИНАКОВОЙ последовательности вызовов несёт ОДИНАКОВЫЙ count."""
        repeats = 5

        mgr_one = StatsManager(manager_name="OneChannel", config={"enable_logging": False})
        mgr_one.initialize()
        mgr_many = StatsManager(manager_name="ManyChannels", config={"enable_logging": False})
        mgr_many.initialize()
        try:
            ch_one = _DummyChannel("solo")
            mgr_one.register_channel(ch_one)
            many_channels = [_DummyChannel(f"m{i}") for i in range(4)]
            for ch in many_channels:
                mgr_many.register_channel(ch)

            for _ in range(repeats):
                mgr_one.increment("ops")
                mgr_many.increment("ops")

            mgr_one.flush()
            mgr_many.flush()

            def _count(ch: _DummyChannel) -> float:
                metrics = ch.received[0].get("metrics", [])
                metric = next(m for m in metrics if m["name"] == "ops")
                return metric["count"]

            expected = _count(ch_one)
            assert expected == float(repeats)
            for ch in many_channels:
                assert _count(ch) == expected, (
                    f"{ch.name}: count={_count(ch)} != {expected} (эталон 1-канального менеджера) "
                    f"— число каналов не должно влиять на посчитанный тотал"
                )
        finally:
            mgr_one.shutdown()
            mgr_many.shutdown()
