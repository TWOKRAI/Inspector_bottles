# -*- coding: utf-8 -*-
"""Характеризация `LoggerCore.log()` ПЕРЕД перестройкой доставки (Ф4.1).

Vision §4 требует снимать поведение до перестройки, а не после. Здесь оно
снято на **нетронутом** коде и прогнано зелёным до единой правки `log()` —
иначе характеризация описывала бы уже переделанное и соглашалась с ним.

Что здесь НЕ проверяется: правильность. Эти тесты не утверждают, что поведение
хорошее — они утверждают, что оно ТАКОЕ. Если 4.1 сознательно меняет какой-то
из пунктов, тест правится вместе с кодом и в коммите называется причина; если
пункт падает неожиданно — это регресс.

Отдельно снято **число вызовов ``to_dict()`` на одну запись**: это единственный
измеримый критерий приёмки 4.1 («один раз на запись независимо от числа
каналов»). Числа зафиксированы литералами, а не выражением от числа каналов:
формула согласилась бы с любым ответом.

**Что изменилось вместе с 4.1 и почему** (класс тестов «база сдвинулась» —
правится вместе с кодом, с названной причиной): цена записи была 2 при одном
tap'е и 3 в батч-цикле на трёх каналах, стала **1** в обоих случаях. Остальные
двенадцать пунктов характеризации переехали через перестройку без правки —
поведение доставки не изменилось, изменилась только цена.
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
        # Ф8.1: параметр помощника значил «порог гейта», и после снятия второй
        # оси он обязан ехать туда, где порог теперь живёт, — в корень. Оставить
        # его прежним аргументом скоупа значило бы получить помощник с мёртвой
        # ручкой: три теста ниже задают ERROR и проверяли бы поведение DEBUG.
        "default_level": min_level,
        "scopes": {"SYSTEM": {"channels": list(channels)}},
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

    def test_tap_does_not_add_a_second_serialization(self, logger_with_spies, monkeypatch) -> None:
        """ПОСЛЕ Ф4.1: tap едет тем же словарём.

        База до правки была **2**: tap собирал свою копию того же содержимого.
        Число изменено вместе с кодом сознательно — это и есть 4.1.
        """
        mgr, _ = logger_with_spies
        mgr.add_tap(_SpyChannel("tap"), min_level="DEBUG", name="tap")
        counter = self._count_to_dict(monkeypatch)

        mgr.log("SYSTEM", LogLevel.INFO, "стоимость с tap", "mod")

        assert counter[0] == 1, (
            f"с одним tap'ом запись сериализуется {counter[0]} раз — цепочка обязана собирать словарь один раз"
        )

    def test_batch_loop_serializes_once_regardless_of_channel_count(self, monkeypatch) -> None:
        """ГЛАВНОЕ число фазы — приёмка 4.1 буквально.

        База до правки была **3** при трёх каналах: словарь собирался ПО РАЗУ
        НА КАНАЛ. Стало **1** — число приёмников на цену сборки не влияет.
        Литерал, а не ``len(channels)``: формула согласилась бы и с прежним
        поведением, и с любым другим.
        """
        config = {
            "app_name": "characterization",
            "enable_batching": True,
            "modules": {},
            "channels": {},
            "default_level": "DEBUG",
            "scopes": {"SYSTEM": {"channels": ["a", "b", "c"]}},
        }
        mgr = LoggerCore(manager_name="BatchCharacterized", config=config)
        mgr.initialize()
        for name in ("a", "b", "c"):
            mgr.register_channel(_SpyChannel(name))
        counter = self._count_to_dict(monkeypatch)

        mgr.log("SYSTEM", LogLevel.INFO, "батч", "mod")

        assert counter[0] == 1, (
            f"в батч-цикле запись сериализуется {counter[0]} раз при трёх каналах — база характеризации сдвинулась"
        )
        mgr.shutdown()


# ---------------------------------------------------------------------------
# Ф4.1: цепочка процессоров — опасности механизма (авторские тесты)
# ---------------------------------------------------------------------------


class TestProcessorChain:
    """Не «работает ли цепочка», а «что она делает, когда идёт не так».

    Три опасности, которые видны только изнутри механизма: перехватчик,
    сломавшийся на горячем пути; законная потеря, ставшая невидимой; и общий
    словарь, который теперь получают ВСЕ приёмники разом.
    """

    def test_processor_sees_the_record_and_can_replace_it(self, logger_with_spies) -> None:
        mgr, spies = logger_with_spies

        def _redact(scope, level, rec):
            return {**rec, "message": "***"}

        mgr.add_processor(_redact)
        mgr.log("SYSTEM", LogLevel.INFO, "секрет", "mod")

        assert spies[0].written[0]["message"] == "***"

    def test_order_is_the_order_of_addition(self, logger_with_spies) -> None:
        mgr, spies = logger_with_spies
        mgr.add_processor(lambda s, lv, r: {**r, "message": r["message"] + "-первый"})
        mgr.add_processor(lambda s, lv, r: {**r, "message": r["message"] + "-второй"})

        mgr.log("SYSTEM", LogLevel.INFO, "запись", "mod")

        assert spies[0].written[0]["message"] == "запись-первый-второй"

    def test_none_absorbs_the_record_and_the_loss_is_counted(self, logger_with_spies) -> None:
        """Законная потеря обязана быть видимой — иначе она неотличима от сбоя."""
        mgr, spies = logger_with_spies
        before = mgr.stats["records_dropped_by_processor"]

        mgr.add_processor(lambda s, lv, r: None)
        mgr.log("SYSTEM", LogLevel.INFO, "поглощаемая", "mod")

        assert spies[0].written == []
        assert mgr.stats["records_dropped_by_processor"] == before + 1

    def test_broken_processor_does_not_swallow_the_record(self, logger_with_spies) -> None:
        """Перехватчик не вправе терять то, что ему дали посмотреть."""
        mgr, spies = logger_with_spies

        def _boom(scope, level, rec):
            raise RuntimeError("процессор развалился")

        mgr.add_processor(_boom)
        mgr.log("SYSTEM", LogLevel.INFO, "уцелевшая", "mod")

        assert len(spies[0].written) == 1
        assert spies[0].written[0]["message"] == "уцелевшая"
        assert mgr.stats["processor_failures"] == 1

    def test_broken_processor_does_not_stop_the_next_one(self, logger_with_spies) -> None:
        mgr, spies = logger_with_spies

        def _boom(scope, level, rec):
            raise RuntimeError("первый упал")

        mgr.add_processor(_boom)
        mgr.add_processor(lambda s, lv, r: {**r, "message": "второй отработал"})
        mgr.log("SYSTEM", LogLevel.INFO, "исходная", "mod")

        assert spies[0].written[0]["message"] == "второй отработал"

    def test_taps_see_the_processed_record_not_the_original(self, logger_with_spies) -> None:
        """Редакция секретов обязана застать запись ДО tap'а: tap уходит оператору."""
        mgr, _ = logger_with_spies
        tap = _SpyChannel("tap")
        mgr.add_tap(tap, min_level="DEBUG", name="tap")
        mgr.add_processor(lambda s, lv, r: {**r, "message": "***"})

        mgr.log("SYSTEM", LogLevel.INFO, "пароль=hunter2", "mod")

        assert tap.written[0]["message"] == "***", "tap увидел незамаскированную запись"

    def test_removing_a_processor_takes_it_out_of_the_chain(self, logger_with_spies) -> None:
        mgr, spies = logger_with_spies

        def _mark(scope, level, rec):
            return {**rec, "message": "помечено"}

        mgr.add_processor(_mark)
        assert mgr.remove_processor(_mark) is True
        assert mgr.remove_processor(_mark) is False, "повторное снятие обязано отвечать False"

        mgr.log("SYSTEM", LogLevel.INFO, "чистая", "mod")

        assert spies[0].written[0]["message"] == "чистая"

    def test_all_channels_receive_equal_content_from_the_shared_dict(self, logger_with_spies) -> None:
        """Словарь теперь ОДИН на все каналы — содержимое обязано совпадать.

        До 4.1 каждый канал получал свою копию как побочный эффект сборки.
        Копию никто не запрашивал, но если какой-то канал начнёт мутировать
        запись, соседи увидят чужую правку — вот проверка этого шва.
        """
        mgr, spies = logger_with_spies

        mgr.log("SYSTEM", LogLevel.INFO, "общая", "mod")

        payloads = [spy.written[0] for spy in spies]
        assert payloads[0] == payloads[1] == payloads[2]
        assert payloads[0]["message"] == "общая"
