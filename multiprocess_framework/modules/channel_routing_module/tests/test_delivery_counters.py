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


def _rate(before: Dict[str, Any], after: Dict[str, Any]) -> float:
    """Темп между двумя снимками — так его считает ПОТРЕБИТЕЛЬ.

    Менеджер темпа не отдаёт: он отдаёт счётчик и момент снимка. Состояние держит
    тот, кто опрашивает.
    """
    dt = after["observed_at"] - before["observed_at"]
    return (after["channel_written_records"] - before["channel_written_records"]) / dt


class TestA2DeliveryRateIsDerivableBySnapshots:
    """A2 (поглощённая 5.2): «уровень включён, записей ноль» ≠ «записи идут».

    Различие даёт ПАРА снимков, а не готовое поле. Менеджер отдаёт монотонный
    счётчик и момент чтения; частное берёт потребитель — так устроен любой scraper
    поверх counter-метрики.

    Так было не сразу. Первая редакция отдавала готовый `observed_rate_per_sec` и
    держала ради него одну базу отсчёта на всех потребителей; в этой системе их
    два (панель GUI и backend_ctl), и они портили показания друг другу. Ни один
    тест этого не поймал: все читали в одиночку. Отсюда стражи ниже — включая тот,
    что читает ДВАЖДЯ чужими глазами.
    """

    def _mgr_with_clock(self):
        clock = _FakeClock()
        mgr = _manager([_Channel("system_file")])
        mgr._clock = clock
        return mgr, clock

    def test_snapshot_carries_counter_and_moment(self) -> None:
        mgr, clock = self._mgr_with_clock()
        snap = _snapshot(mgr)
        assert snap["channel_written_records"] == 0
        assert snap["observed_at"] == clock.now

    def test_silence_between_snapshots_is_zero_rate(self) -> None:
        mgr, clock = self._mgr_with_clock()
        first = _snapshot(mgr)
        clock.now += 10.0
        assert _rate(first, _snapshot(mgr)) == 0.0

    def test_flow_between_snapshots_is_positive_literal(self) -> None:
        """Литерал, а не «поле присутствует»: 20 записей за 10с → 2.0/с."""
        mgr, clock = self._mgr_with_clock()
        first = _snapshot(mgr)
        for _ in range(20):
            mgr._write_record_to_channels({"msg": "x"}, ["system_file"])
        clock.now += 10.0
        assert _rate(first, _snapshot(mgr)) == 2.0

    def test_flow_then_silence_is_distinguishable(self) -> None:
        """«Записи шли и перестали» отличимо от «записи идут» — та самая пара."""
        mgr, clock = self._mgr_with_clock()
        first = _snapshot(mgr)
        for _ in range(20):
            mgr._write_record_to_channels({"msg": "x"}, ["system_file"])
        clock.now += 10.0
        busy = _snapshot(mgr)
        assert _rate(first, busy) == 2.0
        clock.now += 10.0
        assert _rate(busy, _snapshot(mgr)) == 0.0

    def test_two_independent_readers_do_not_corrupt_each_other(self) -> None:
        """СТРАЖ на исправленный дефект: два потребителя не мешают друг другу.

        Прежняя редакция держала одну базу отсчёта внутри менеджера и сдвигала её
        на каждом чтении. Читатель B получал интервал «с последнего чтения A», то
        есть число зависело от постороннего наблюдателя. Здесь A читает часто, B
        редко — и B обязан увидеть СВОЙ интервал целиком.
        """
        mgr, clock = self._mgr_with_clock()
        b_start = _snapshot(mgr)  # редкий читатель взял базу
        for _ in range(10):
            mgr._write_record_to_channels({"msg": "x"}, ["system_file"])
        clock.now += 5.0
        _snapshot(mgr)  # частый читатель A вклинился
        _snapshot(mgr)  # и ещё раз
        for _ in range(10):
            mgr._write_record_to_channels({"msg": "x"}, ["system_file"])
        clock.now += 5.0
        _snapshot(mgr)  # A снова
        b_end = _snapshot(mgr)  # редкий читатель B закрывает свой интервал
        # 20 записей за 10 секунд — независимо от того, сколько раз читал A.
        assert _rate(b_start, b_end) == 2.0

    def test_repeated_snapshots_do_not_change_the_counter(self) -> None:
        """Чтение не мутирует наблюдаемое.

        Вторая половина стража выше: если снимок сдвигает состояние, «два
        независимых читателя» можно было бы получить и случайно.
        """
        mgr, _ = self._mgr_with_clock()
        for _ in range(7):
            mgr._write_record_to_channels({"msg": "x"}, ["system_file"])
        totals = [_snapshot(mgr)["channel_written_records"] for _ in range(4)]
        assert totals == [7, 7, 7, 7], f"чтение изменило счётчик: {totals}"

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


class TestA3TheOnlyWritePathAccounts:
    """A3: учёт есть на дороге записи — теперь она ровно одна.

    Ф7.4: батчевый путь (`_flush_batch`) снят вместе с батчингом, поэтому пара
    «обе дороги считают одинаково» выродилась в одну дорогу. Свойство осталось
    прежним и проверяется на ней: доставка считается, отсутствие канала —
    по-записно в потерю, а не в доставку.
    """

    def _core(self):
        from multiprocess_framework.modules.logger_module.configs import LoggerManagerConfig
        from multiprocess_framework.modules.logger_module.core.logger_core import LoggerCore

        return LoggerCore(config=LoggerManagerConfig(app_name="t"))

    def test_direct_path_counts_delivery(self) -> None:
        core = self._core()
        try:
            ch = _Channel("system_file")
            core._channel_registry.register(ch)
            assert core._write_record_to_channels({"m": 1}, ["system_file"]) == 1
            snap = core._loss_counters_snapshot()
            assert snap["channel_written_records"] == 1
            assert snap["channel_written_by_channel"] == {"system_file": 1}
        finally:
            core.shutdown()

    def test_missing_channel_is_not_delivery(self) -> None:
        core = self._core()
        try:
            assert core._write_record_to_channels({"m": 1}, ["ghost"]) == 0
            snap = core._loss_counters_snapshot()
            assert snap["channel_written_records"] == 0
            assert snap["unresolved_channel_records"] == 1, "потеря считается по-записно"
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

        for key in ("channel_written_records", "channel_written_by_channel", "observed_at"):
            assert key in PLANE_COUNTER_KEYS, f"{key} не публикуется наружу"
