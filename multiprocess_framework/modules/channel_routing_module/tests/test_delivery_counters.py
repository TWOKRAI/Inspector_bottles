# -*- coding: utf-8 -*-
"""Task 5.6 — счётчик доставки: «включён» отличимо от «доставляет».

До 5.6 все счётчики трёх плоскостей считали ТОЛЬКО потери, и «потерь ноль»
одинаково означало здоровую систему и систему, из которой ничего не выходит.
Успех вычислялся (`written` в обеих дорогах записи) и выбрасывался.

Каждая гарантия проверяется ПАРОЙ: без второй половины тест был бы зелен и у
реализации «считать всегда, независимо от исхода» — то есть стерёг бы наличие
поля, а не смысл.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from multiprocess_framework.modules.channel_routing_module.core.channel_routing_manager import (
    RATE_MIN_INTERVAL_SEC,
    ChannelRoutingManager,
)
from multiprocess_framework.modules.channel_routing_module.interfaces import IChannel


class _Channel(IChannel):
    """Приёмник с управляемым исходом: принял / отказал статусом / бросил.

    Наследует ``IChannel`` не для красоты: реестр проверяет ``isinstance``, и
    самодельный duck-type объект он молча не регистрирует — запись тогда уходит
    в «канал не резолвится», и тест доказывал бы потерю вместо доставки.
    """

    def __init__(self, name: str, *, outcome: str = "accept") -> None:
        self._name = name
        self.outcome = outcome
        self.written: List[Dict] = []

    @property
    def name(self) -> str:
        return self._name

    def write(self, record: Dict) -> Any:
        if self.outcome == "raise":
            raise RuntimeError("сток сломан")
        if self.outcome == "refuse":
            return {"status": "error"}
        self.written.append(record)
        return {"status": "ok"}

    def close(self) -> None:
        pass


class _FakeClock:
    """Часы как ЗАВИСИМОСТЬ объекта.

    Глобальный патч `time.monotonic` с конечным side_effect доедают чужие потоки,
    и StopIteration вылетает в невиновном тесте — отдельный урок проекта.
    """

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def _manager(channels: Optional[List[_Channel]] = None) -> ChannelRoutingManager:
    mgr = ChannelRoutingManager("delivery_probe")
    for ch in channels or []:
        mgr._channel_registry.register(ch)
    return mgr


def _snapshot(mgr: ChannelRoutingManager) -> Dict[str, Any]:
    return mgr._loss_counters_snapshot()


class TestA1DeliveryIsCountedOnlyWhenItHappens:
    """A1: счётчик растёт на доставке — и НЕ растёт, когда доставки не было."""

    def test_accepted_record_increments_written(self) -> None:
        ch = _Channel("system_file")
        mgr = _manager([ch])
        assert mgr._write_record_to_channels({"msg": "x"}, ["system_file"]) == 1
        snap = _snapshot(mgr)
        assert snap["channel_written_records"] == 1
        assert snap["channel_written_by_channel"] == {"system_file": 1}

    def test_missing_channel_counts_loss_not_delivery(self) -> None:
        """Вторая половина: несуществующий приёмник — потеря, а не доставка."""
        mgr = _manager()
        assert mgr._write_record_to_channels({"msg": "x"}, ["ghost"]) == 0
        snap = _snapshot(mgr)
        assert snap["channel_written_records"] == 0, "потеря учтена как доставка"
        assert snap["channel_written_by_channel"] == {}
        assert snap["unresolved_channel_records"] == 1

    def test_refused_record_counts_loss_not_delivery(self) -> None:
        """Канал ЖИВ, но записи не принял — это не доставка."""
        mgr = _manager([_Channel("console", outcome="refuse")])
        assert mgr._write_record_to_channels({"msg": "x"}, ["console"]) == 0
        snap = _snapshot(mgr)
        assert snap["channel_written_records"] == 0
        assert snap["channel_refused_records"] == 1

    def test_raising_channel_counts_loss_not_delivery(self) -> None:
        mgr = _manager([_Channel("broken", outcome="raise")])
        assert mgr._write_record_to_channels({"msg": "x"}, ["broken"]) == 0
        snap = _snapshot(mgr)
        assert snap["channel_written_records"] == 0
        assert snap["channel_write_errors"] == 1

    def test_partial_delivery_names_the_survivor(self) -> None:
        """Один приёмник принял, второй мёртв — обе половины видны раздельно.

        Это и есть ответ на вопрос, который в коде висел незакрытым: «легла ли
        запись хоть куда-нибудь». По сумме потерь он неотличим от полной потери.
        """
        mgr = _manager([_Channel("system_file"), _Channel("console", outcome="refuse")])
        assert mgr._write_record_to_channels({"msg": "x"}, ["system_file", "console", "ghost"]) == 1
        snap = _snapshot(mgr)
        assert snap["channel_written_by_channel"] == {"system_file": 1}
        assert snap["channel_refused_by_channel"] == {"console": 1}
        assert snap["unresolved_channels"] == {"ghost": 1}


class TestA2ObservedRateDistinguishesSilence:
    """A2 (поглощённая 5.2): «уровень включён, записей ноль» ≠ «записи идут».

    Темп производный от монотонного счётчика и считается ПРИ ЧТЕНИИ (решение Р2 —
    замер показал, что окно на горячем пути стоило дороже самого учёта). Поэтому
    первое чтение задаёт базу и честно отдаёт ноль, а различие видно со второго.
    """

    def _mgr_with_clock(self):
        clock = _FakeClock()
        mgr = _manager([_Channel("system_file")])
        mgr._clock = clock
        return mgr, clock

    def test_first_read_sets_the_baseline_and_returns_zero(self) -> None:
        mgr, _ = self._mgr_with_clock()
        assert _snapshot(mgr)["observed_rate_per_sec"] == 0.0

    def test_silence_between_reads_reads_as_zero(self) -> None:
        """Ничего не писали между чтениями → ровно ноль, а не «прежний темп»."""
        mgr, clock = self._mgr_with_clock()
        _snapshot(mgr)  # база
        clock.now += 10.0
        assert _snapshot(mgr)["observed_rate_per_sec"] == 0.0

    def test_flow_between_reads_reads_as_positive_literal(self) -> None:
        """Литерал, а не «поле присутствует»: 20 записей за 10с → 2.0/с."""
        mgr, clock = self._mgr_with_clock()
        _snapshot(mgr)  # база
        for _ in range(20):
            mgr._write_record_to_channels({"msg": "x"}, ["system_file"])
        clock.now += 10.0
        assert _snapshot(mgr)["observed_rate_per_sec"] == 2.0

    def test_silence_after_flow_returns_to_zero(self) -> None:
        """«Записи шли и перестали» отличимо от «записи идут».

        Ровно та неотличимость, ради устранения которой задача и делается.
        """
        mgr, clock = self._mgr_with_clock()
        _snapshot(mgr)
        for _ in range(20):
            mgr._write_record_to_channels({"msg": "x"}, ["system_file"])
        clock.now += 10.0
        assert _snapshot(mgr)["observed_rate_per_sec"] == 2.0
        clock.now += 10.0
        assert _snapshot(mgr)["observed_rate_per_sec"] == 0.0, "молчание отдало прежний темп"

    def test_rate_counts_only_the_interval_not_all_history(self) -> None:
        """Второй интервал считается по своим записям, а не по всей истории."""
        mgr, clock = self._mgr_with_clock()
        _snapshot(mgr)
        for _ in range(10):
            mgr._write_record_to_channels({"msg": "a"}, ["system_file"])
        clock.now += 10.0
        assert _snapshot(mgr)["observed_rate_per_sec"] == 1.0
        for _ in range(30):
            mgr._write_record_to_channels({"msg": "b"}, ["system_file"])
        clock.now += 10.0
        # 30 за 10с, а не 40 за 20с.
        assert _snapshot(mgr)["observed_rate_per_sec"] == 3.0

    def test_too_frequent_read_does_not_zero_the_rate_it_measures(self) -> None:
        """Частый опрос не обнуляет измеряемое.

        Сдвигай базу при каждом чтении — и опрос дважды подряд показал бы ноль
        просто потому, что между двумя чтениями ничего не успело произойти. То
        есть инструмент наблюдения ломал бы наблюдаемое.
        """
        mgr, clock = self._mgr_with_clock()
        _snapshot(mgr)
        for _ in range(20):
            mgr._write_record_to_channels({"msg": "x"}, ["system_file"])
        clock.now += 10.0
        first = _snapshot(mgr)["observed_rate_per_sec"]
        assert first == 2.0
        clock.now += RATE_MIN_INTERVAL_SEC / 2  # слишком быстро
        assert _snapshot(mgr)["observed_rate_per_sec"] == first

    def test_no_clock_call_on_the_write_path(self) -> None:
        """Горячий путь не спрашивает часы вовсе (решение Р2 — цена).

        Спай на счётчике вызовов часов, а не на имени метода: гарантия здесь —
        «часы не дёргаются на записи», и она обязана переживать переименование
        внутренностей.
        """
        mgr = _manager([_Channel("system_file")])
        calls = {"n": 0}

        def counting_clock() -> float:
            calls["n"] += 1
            return 1000.0

        mgr._clock = counting_clock
        for _ in range(50):
            mgr._write_record_to_channels({"msg": "x"}, ["system_file"])
        assert calls["n"] == 0, f"часы вызваны {calls['n']} раз на пути записи"


class TestA3BothWritePathsAccount:
    """A3: учёт есть на ОБЕИХ дорогах записи, а не на одной из двух."""

    def test_batched_path_counts_delivery(self) -> None:
        """Батчевый путь логгера (`_flush_batch`) — своя дорога, тот же счётчик.

        Дефект, починенный на одном пути из двух, — класс, по которому проект
        уже бился; поэтому путь проверяется своим тестом, а не «по аналогии».
        """
        from multiprocess_framework.modules.logger_module.configs import LoggerManagerConfig
        from multiprocess_framework.modules.logger_module.core.logger_core import LoggerCore

        core = LoggerCore(config=LoggerManagerConfig(app_name="t", enable_batching=True))
        try:
            ch = _Channel("system_file")
            core._channel_registry.register(ch)
            assert core._flush_batch("system_file", [{"m": 1}, {"m": 2}, {"m": 3}]) == 3
            snap = core._loss_counters_snapshot()
            assert snap["channel_written_records"] == 3
            assert snap["channel_written_by_channel"] == {"system_file": 3}
        finally:
            core.shutdown()

    def test_batched_path_missing_channel_is_not_delivery(self) -> None:
        from multiprocess_framework.modules.logger_module.configs import LoggerManagerConfig
        from multiprocess_framework.modules.logger_module.core.logger_core import LoggerCore

        core = LoggerCore(config=LoggerManagerConfig(app_name="t", enable_batching=True))
        try:
            assert core._flush_batch("ghost", [{"m": 1}, {"m": 2}]) == 0
            snap = core._loss_counters_snapshot()
            assert snap["channel_written_records"] == 0
            assert snap["unresolved_channel_records"] == 2, "потеря считается по-записно"
        finally:
            core.shutdown()


class TestCountersArePublishedOutward:
    """Счётчик, которого нет в readback, существует и при этом невидим.

    Ф0.3 уже стреляла этим классом, поэтому реестр публикации проверяется
    отдельно от самого механизма.
    """

    def test_delivery_keys_are_in_the_published_registry(self) -> None:
        from multiprocess_framework.modules.process_module.managers.observability_reload import (
            PLANE_COUNTER_KEYS,
        )

        for key in ("channel_written_records", "channel_written_by_channel", "observed_rate_per_sec"):
            assert key in PLANE_COUNTER_KEYS, f"{key} не публикуется наружу"
