# -*- coding: utf-8 -*-
"""Характеризация `LoggerCore.log()` ПЕРЕД перестройкой доставки (Ф4.1).

Vision §4 требует снимать поведение до перестройки, а не после. Здесь оно
снято на **нетронутом** коде и прогнано зелёным до единой правки `log()` —
иначе характеризация описывала бы уже переделанное и соглашалась с ним.

Что здесь НЕ проверяется: правильность. Эти тесты не утверждают, что поведение
хорошее — они утверждают, что оно ТАКОЕ. Если 4.1 сознательно меняет какой-то
из пунктов, тест правится вместе с кодом и в коммите называется причина; если
пункт падает неожиданно — это регресс.

Отдельно снят **число вызовов ``to_dict()`` на одну запись**: это единственный
измеримый критерий приёмки 4.1 («один раз на запись независимо от числа
каналов»). База зафиксирована ниже литералом, а не выражением от числа каналов:
формула согласилась бы с любым ответом, включая нынешний.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.channel_routing_module.interfaces import IChannel
from multiprocess_framework.modules.logger_module.core.log_types import LogLevel, LogRecord
from multiprocess_framework.modules.logger_module.core.logger_core import LoggerCore


class _SpyChannel(IChannel):
    """Канал, записывающий всё принятое.

    Наследование от ``IChannel`` не формальность: реестр отвергает утиный тип
    (``isinstance``-проверка), и регистрация молча вернула бы False — записи
    поехали бы мимо наблюдения, а тест «проверял» бы пустоту.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self.written: List[Dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return "spy"

    def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
        self.written.append(data)
        return {"status": "success", "channel": self._name}

    def close(self) -> None:
        pass


def _logger(channels: List[str], min_level: str = "DEBUG") -> LoggerCore:
    """Логгер без буфера: запись едет прямо в каналы, путь наблюдаем целиком."""
    config = {
        "app_name": "characterization",
        "enable_batching": False,
        "modules": {},
        # Каналы НЕ объявляются конфигом: их регистрирует тест шпионами под
        # теми же именами. Объявленные конфигом заняли бы имена, и
        # register_channel вернул бы False — запись поехала бы в memory-каналы
        # мимо наблюдения.
        "channels": {},
        "scopes": {"SYSTEM": {"enabled": True, "min_level": min_level, "channels": list(channels)}},
    }
    mgr = LoggerCore(manager_name="CharacterizedLogger", config=config)
    mgr.initialize()
    return mgr


@pytest.fixture
def logger_with_spies():
    """Три канала-шпиона на одном скоупе — число приёмников тут существенно."""
    mgr = _logger(["a", "b", "c"])
    spies = []
    for name in ("a", "b", "c"):
        spy = _SpyChannel(name)
        mgr.register_channel(spy)
        spies.append(spy)
    yield mgr, spies
    mgr.shutdown()


class TestDeliveryShape:
    def test_record_reaches_every_channel_of_the_scope(self, logger_with_spies) -> None:
        mgr, spies = logger_with_spies

        mgr.log("SYSTEM", LogLevel.INFO, "привет", "mod")

        for spy in spies:
            assert len(spy.written) == 1, f"канал {spy.name} не получил запись"

    def test_all_channels_get_the_same_content(self, logger_with_spies) -> None:
        """Запись общая для всех приёмников — это и есть посылка «собрать один раз»."""
        mgr, spies = logger_with_spies

        mgr.log("SYSTEM", LogLevel.INFO, "одно и то же", "mod")

        payloads = [spy.written[0] for spy in spies]
        assert payloads[0]["message"] == payloads[1]["message"] == payloads[2]["message"]
        assert payloads[0]["seq"] == payloads[1]["seq"] == payloads[2]["seq"]

    def test_gate_rejects_below_threshold_and_counts_it(self) -> None:
        mgr = _logger(["a"], min_level="ERROR")
        spy = _SpyChannel("a")
        mgr.register_channel(spy)
        before = mgr.stats["messages_skipped"]

        mgr.log("SYSTEM", LogLevel.DEBUG, "ниже порога", "mod")

        assert spy.written == []
        assert mgr.stats["messages_skipped"] == before + 1
        mgr.shutdown()

    def test_processed_counter_counts_the_call_not_the_delivery(self) -> None:
        """``messages_processed`` растёт ДО гейта — считает попытки, не доставки."""
        mgr = _logger(["a"], min_level="ERROR")
        mgr.register_channel(_SpyChannel("a"))
        before = mgr.stats["messages_processed"]

        mgr.log("SYSTEM", LogLevel.DEBUG, "отклонённая", "mod")

        assert mgr.stats["messages_processed"] == before + 1
        mgr.shutdown()


class TestRecordContent:
    def test_extra_is_merged_into_the_record(self, logger_with_spies) -> None:
        mgr, spies = logger_with_spies

        mgr.log("SYSTEM", LogLevel.INFO, "с контекстом", "mod", trace_id="abc123")

        assert spies[0].written[0]["extra"]["trace_id"] == "abc123"

    def test_module_travels_with_the_record(self, logger_with_spies) -> None:
        mgr, spies = logger_with_spies

        mgr.log("SYSTEM", LogLevel.INFO, "имя источника", "camera_0")

        assert spies[0].written[0]["module"] == "camera_0"

    def test_seq_is_monotonic_across_records(self, logger_with_spies) -> None:
        """Пломба 2.V1: номер растёт и ставится ПОСЛЕ гейта."""
        mgr, spies = logger_with_spies

        mgr.log("SYSTEM", LogLevel.INFO, "первая", "mod")
        mgr.log("SYSTEM", LogLevel.INFO, "вторая", "mod")

        first, second = spies[0].written[0]["seq"], spies[0].written[1]["seq"]
        assert second > first

    def test_deferred_message_is_called_once_after_the_gate(self, logger_with_spies) -> None:
        mgr, spies = logger_with_spies
        calls = []

        mgr.log("SYSTEM", LogLevel.INFO, lambda: calls.append(1) or "отложенное", "mod")

        assert len(calls) == 1, "отложенное сообщение собрано не один раз"

    def test_deferred_message_is_not_called_when_the_gate_rejects(self) -> None:
        mgr = _logger(["a"], min_level="ERROR")
        mgr.register_channel(_SpyChannel("a"))
        calls = []

        mgr.log("SYSTEM", LogLevel.DEBUG, lambda: calls.append(1) or "дорогое", "mod")

        assert calls == [], "дорогая сборка выполнена для записи, которую гейт отклонил"
        mgr.shutdown()

    def test_broken_message_builder_does_not_reach_the_caller(self, logger_with_spies) -> None:
        """Политика: упавшая сборка сохраняет запись, а не теряет её и не роняет эмитента."""
        mgr, spies = logger_with_spies

        def _boom():
            raise RuntimeError("сборка развалилась")

        mgr.log("SYSTEM", LogLevel.INFO, _boom, "mod")

        assert len(spies[0].written) == 1
        assert "сборка сообщения упала" in spies[0].written[0]["message"]


class TestSerializationCost:
    """Цена записи в вызовах ``to_dict()`` — критерий приёмки 4.1.

    Число снято ЛИТЕРАЛОМ на нынешнем коде. Выражение вида
    ``len(channels) + 1`` согласилось бы и с текущим поведением, и с любым
    другим — то есть не проверяло бы ничего.
    """

    def _count_to_dict(self, monkeypatch) -> List[int]:
        counter = [0]
        original = LogRecord.to_dict

        def _counting(self, *a, **kw):
            counter[0] += 1
            return original(self, *a, **kw)

        monkeypatch.setattr(LogRecord, "to_dict", _counting)
        return counter

    def test_baseline_cost_with_three_channels_and_no_taps(self, logger_with_spies, monkeypatch) -> None:
        mgr, _ = logger_with_spies
        counter = self._count_to_dict(monkeypatch)

        mgr.log("SYSTEM", LogLevel.INFO, "стоимость", "mod")

        assert counter[0] == 1, (
            f"без буфера и без tap'ов запись сериализуется {counter[0]} раз — база характеризации сдвинулась"
        )

    def test_baseline_cost_with_taps_attached(self, logger_with_spies, monkeypatch) -> None:
        """Tap добавляет СВОЮ сериализацию — вот она, вторая сборка того же словаря."""
        mgr, _ = logger_with_spies
        mgr.add_tap(_SpyChannel("tap"), min_level="DEBUG", name="tap")
        counter = self._count_to_dict(monkeypatch)

        mgr.log("SYSTEM", LogLevel.INFO, "стоимость с tap", "mod")

        assert counter[0] == 2, f"с одним tap'ом запись сериализуется {counter[0]} раз — база характеризации сдвинулась"

    def test_baseline_cost_in_the_batch_loop(self, monkeypatch) -> None:
        """ГЛАВНОЕ число фазы: в батч-цикле словарь собирается ПО РАЗУ НА КАНАЛ.

        Ради этого 4.1 и заводилась («``to_dict()`` один раз на запись
        независимо от числа каналов»). Три канала — три сериализации одного и
        того же содержимого.
        """
        config = {
            "app_name": "characterization",
            "enable_batching": True,
            "modules": {},
            "channels": {},
            "scopes": {"SYSTEM": {"enabled": True, "min_level": "DEBUG", "channels": ["a", "b", "c"]}},
        }
        mgr = LoggerCore(manager_name="BatchCharacterized", config=config)
        mgr.initialize()
        for name in ("a", "b", "c"):
            mgr.register_channel(_SpyChannel(name))
        counter = self._count_to_dict(monkeypatch)

        mgr.log("SYSTEM", LogLevel.INFO, "батч", "mod")

        assert counter[0] == 3, (
            f"в батч-цикле запись сериализуется {counter[0]} раз при трёх каналах — база характеризации сдвинулась"
        )
        mgr.shutdown()
