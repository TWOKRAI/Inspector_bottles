# -*- coding: utf-8 -*-
"""Task 2.9 — приёмники «память процесса» (`memory`) и «никуда» (`null`).

Проверяется ровно то, что заявлено приёмкой:

* новый тип заводится **конфигом**, без правок кода фреймворка;
* последние N записей читаются командой из живого процесса;
* запись в `null` не увеличивает НИ ОДИН класс потерь;
* вырожденный случай (скоуп ERROR только в `null`) не запрещён, но
  конфигурация обязана сказать об этом вслух.

Плюс опасности самого механизма, видимые только автору: вытеснение из кольца
не должно попасть в потери, кривая ёмкость не должна дать тихо пропавший лог,
а кольцо не должно разделять изменяемый словарь с вызывающим.
"""

from __future__ import annotations

import logging

import pytest

from multiprocess_framework.modules.channel_routing_module.core.channel_routing_manager import (
    LOSS_COUNTER_KEYS,
)
from multiprocess_framework.modules.logger_module.channels.log_channel import (
    LogChannel,
    MemoryChannel,
    NullChannel,
    create_channel,
    get_registered_sink_types,
    register_sink_factory,
    _SINK_FACTORIES,
)
from multiprocess_framework.modules.logger_module.configs import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

#: Имя stdlib-логгера, под которым пишет аварийная функция из `_fallback_log`.
_EMERGENCY_LOGGER = "multiprocess_framework.modules.channel_routing_module.core.channel_routing_manager"


def _record(message: str = "x", level: str = "INFO") -> dict:
    return {"timestamp": 0.0, "level": level, "message": message, "module": "m", "extra": {}}


def _manager(tmp_path, channels: dict, scopes: dict) -> LoggerManager:
    return LoggerManager(
        config=LoggerManagerConfig(
            app_name="sink29",
            log_directory=str(tmp_path),
            enable_batching=False,
            modules={},
            channels=channels,
            scopes=scopes,
        )
    )


def _losses(mgr: LoggerManager) -> dict:
    stats = mgr.get_stats()
    return {key: stats.get(key, 0) for key in LOSS_COUNTER_KEYS}


# =============================================================================
# Механизм расширения
# =============================================================================


class TestSinkTypesAreConfigurable:
    def test_both_new_types_are_registered(self) -> None:
        types = get_registered_sink_types()
        assert "memory" in types
        assert "null" in types

    def test_a_brand_new_type_needs_no_framework_edit(self, tmp_path) -> None:
        """Приёмка: свой приёмник заводится регистрацией + конфигом.

        Ни `create_channel`, ни схема канала не правятся — тип это свободная
        строка, а фабрика берётся из реестра.
        """
        written: list = []

        class ShoutChannel(LogChannel):
            def write(self, record):
                written.append(record["message"])
                return {"status": "success", "channel": self.name}

        register_sink_factory("shout_29", ShoutChannel)
        try:
            mgr = _manager(
                tmp_path,
                channels={"loud": LoggerChannelSchema(type="shout_29")},
                scopes={"SYSTEM": LoggerScopeSchema(min_level="INFO", channels=["loud"])},
            )
            try:
                mgr.info("привет", module="m")
                assert written == ["привет"]
            finally:
                mgr.shutdown()
        finally:
            _SINK_FACTORIES.pop("shout_29", None)


# =============================================================================
# Кольцо в памяти
# =============================================================================


class TestMemoryChannel:
    def test_tail_returns_the_last_n_in_order(self) -> None:
        ch = MemoryChannel(LoggerChannelSchema(name="mem", type="memory", capacity=10))
        for i in range(5):
            ch.write(_record(f"m{i}"))

        assert [r["message"] for r in ch.tail(2)] == ["m3", "m4"]
        assert [r["message"] for r in ch.tail()] == ["m0", "m1", "m2", "m3", "m4"]
        assert ch.tail(0) == []

    def test_capacity_bounds_the_ring_and_eviction_is_counted(self) -> None:
        ch = MemoryChannel(LoggerChannelSchema(name="mem", type="memory", capacity=3))
        for i in range(10):
            ch.write(_record(f"m{i}"))

        info = ch.get_info()
        assert info["size"] == 3
        assert info["capacity"] == 3
        assert info["written"] == 10
        # Ровно 7, а не «сколько-то»: вытеснение начинается с 4-й записи.
        assert info["evicted"] == 7
        assert [r["message"] for r in ch.tail()] == ["m7", "m8", "m9"]

    def test_the_ring_does_not_share_a_mutable_dict_with_the_caller(self) -> None:
        """Словарь, отданный на запись, вызывающий вправе переиспользовать."""
        ch = MemoryChannel(LoggerChannelSchema(name="mem", type="memory", capacity=4))
        record = _record("исходное")
        ch.write(record)
        record["message"] = "подменённое"

        assert ch.tail(1)[0]["message"] == "исходное"

    def test_eviction_is_not_a_loss(self, tmp_path) -> None:
        """Кольцо на 2 записи, отдано 5 — ни один класс потерь не растёт.

        Оператор, задавший ёмкость, ровно это и заказал. Если бы вытеснение
        попало в потери, аномалия «тишина в покое» (2.V2) кричала бы на штатную
        работу — тот же дефект, который закрывала 2.8 для снятого приёмника.
        """
        mgr = _manager(
            tmp_path,
            channels={"mem": LoggerChannelSchema(type="memory", capacity=2)},
            scopes={"SYSTEM": LoggerScopeSchema(min_level="INFO", channels=["mem"])},
        )
        try:
            for i in range(5):
                mgr.info(f"m{i}", module="m")

            assert _losses(mgr) == dict.fromkeys(LOSS_COUNTER_KEYS, 0)
            channel = mgr._channel_registry.get("mem")
            info = channel.get_info()
            assert info["written"] == 5
            assert info["evicted"] == 3
            assert [r["message"] for r in channel.tail()] == ["m3", "m4"]
        finally:
            mgr.shutdown()

    def test_broken_capacity_kills_the_channel_instead_of_silencing_the_log(self, tmp_path) -> None:
        """Ёмкость 0 — это опечатка, а не «кольцо на ноль записей».

        Тихо подставить дефолт или молча выключить канал значило бы превратить
        ошибку конфига в пропавший лог. Канал не создаётся, и записи к нему
        уходят в счётчик — отказ виден.
        """
        with pytest.raises(ValueError):
            create_channel("mem", LoggerChannelSchema(type="memory", capacity=0))

        mgr = _manager(
            tmp_path,
            channels={"mem": LoggerChannelSchema(type="memory", capacity=0)},
            scopes={"SYSTEM": LoggerScopeSchema(min_level="INFO", channels=["mem"])},
        )
        try:
            assert mgr._channel_registry.get("mem") is None
            for _ in range(4):
                mgr.info("m", module="m")

            assert _losses(mgr)["unresolved_channel_records"] == 4
        finally:
            mgr.shutdown()


# =============================================================================
# «Никуда»
# =============================================================================


class TestNullChannel:
    def test_writing_to_null_is_delivery_not_loss(self, tmp_path) -> None:
        mgr = _manager(
            tmp_path,
            channels={"nowhere": LoggerChannelSchema(type="null")},
            scopes={"SYSTEM": LoggerScopeSchema(min_level="INFO", channels=["nowhere"])},
        )
        try:
            for _ in range(7):
                mgr.info("шум", module="m")

            assert _losses(mgr) == dict.fromkeys(LOSS_COUNTER_KEYS, 0)
            assert mgr._channel_registry.get("nowhere").get_info()["written"] == 7
        finally:
            mgr.shutdown()

    def test_null_stores_nothing_to_read(self) -> None:
        ch = NullChannel(LoggerChannelSchema(name="nowhere", type="null"))
        ch.write(_record())
        assert not hasattr(ch, "tail")


class TestNullOnTheErrorPathIsAnnounced:
    """Вырожденный случай: `null` рапортует успех, поэтому пол ошибок молчит."""

    def test_an_error_scope_routed_only_to_null_warns_at_setup(self, tmp_path, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger=_EMERGENCY_LOGGER):
            mgr = _manager(
                tmp_path,
                channels={"nowhere": LoggerChannelSchema(type="null")},
                scopes={"SYSTEM": LoggerScopeSchema(min_level="INFO", channels=["nowhere"])},
            )
        try:
            text = caplog.text
            assert "SYSTEM" in text
            assert "null" in text
        finally:
            mgr.shutdown()

    def test_the_warning_is_about_something_real(self, tmp_path) -> None:
        """Характеризация: ошибка действительно исчезает при чистых счётчиках.

        Без этого предупреждение было бы про воображаемую опасность. Пол ошибок
        ловит запись БЕЗ каналов; здесь канал есть и отвечает успехом, поэтому
        floor остаётся пуст, а все четыре класса потерь — нулевыми.
        """
        mgr = _manager(
            tmp_path,
            channels={"nowhere": LoggerChannelSchema(type="null")},
            scopes={"SYSTEM": LoggerScopeSchema(min_level="INFO", channels=["nowhere"])},
        )
        try:
            before = mgr.get_stats().get("errors_to_floor", 0)
            mgr.error("упало важное", module="m")

            assert mgr.get_stats().get("errors_to_floor", 0) == before
            assert _losses(mgr) == dict.fromkeys(LOSS_COUNTER_KEYS, 0)
            assert mgr._channel_registry.get("nowhere").get_info()["written"] == 1
        finally:
            mgr.shutdown()

    def test_a_scope_with_a_live_file_alongside_null_is_not_warned_about(self, tmp_path, caplog) -> None:
        """Заглушен маршрут, а не отдельный приёмник: пока жив файл — тревоги нет."""
        with caplog.at_level(logging.WARNING, logger=_EMERGENCY_LOGGER):
            mgr = _manager(
                tmp_path,
                channels={
                    "nowhere": LoggerChannelSchema(type="null"),
                    "real": LoggerChannelSchema(type="file", file_path="real.log"),
                },
                scopes={"SYSTEM": LoggerScopeSchema(min_level="INFO", channels=["nowhere", "real"])},
            )
        try:
            assert "null-приёмники" not in caplog.text
        finally:
            mgr.shutdown()

    def test_a_scope_whose_channels_do_not_exist_is_not_called_silenced(self, tmp_path, caplog) -> None:
        """«Приёмников нет» — это случай пола и счётчиков, а не «никуда».

        Граница узкая и легко теряется: `all()` на пустом наборе истинно, и без
        явной проверки живых каналов предупреждение про null сыпалось бы на
        любой скоуп с опечаткой в имени канала — то есть тревога уводила бы
        от настоящей причины.
        """
        with caplog.at_level(logging.WARNING, logger=_EMERGENCY_LOGGER):
            mgr = _manager(
                tmp_path,
                channels={"nowhere": LoggerChannelSchema(type="null")},
                scopes={"SYSTEM": LoggerScopeSchema(min_level="INFO", channels=["__опечатка__"])},
            )
        try:
            assert "null-приёмники" not in caplog.text
        finally:
            mgr.shutdown()

    def test_the_error_plane_checks_its_own_severity_map(self, tmp_path, caplog) -> None:
        """У плоскости ошибок маршрут не скоупный — она смотрит свою карту.

        Проверка родителя ходит по скоупам, а у этой плоскости приёмников в
        скоупах нет по определению: без собственной проверки ERROR, уведённый
        в «никуда», ушёл бы молча.
        """
        from multiprocess_framework.modules.error_module.core.error_manager import ErrorManager

        with caplog.at_level(logging.WARNING, logger=_EMERGENCY_LOGGER):
            mgr = ErrorManager(
                config=LoggerManagerConfig(
                    app_name="err29",
                    log_directory=str(tmp_path),
                    enable_batching=False,
                    modules={},
                    channels={"errors_file": LoggerChannelSchema(type="null")},
                    scopes={},
                )
            )
        try:
            assert "severity-маршрут ERROR" in caplog.text
        finally:
            mgr.shutdown()


# =============================================================================
# Чтение хвоста
# =============================================================================


class TestReadSinkTail:
    def test_reads_the_tail_of_a_memory_sink(self, tmp_path) -> None:
        mgr = _manager(
            tmp_path,
            channels={"mem": LoggerChannelSchema(type="memory", capacity=50)},
            scopes={"SYSTEM": LoggerScopeSchema(min_level="INFO", channels=["mem"])},
        )
        try:
            for i in range(4):
                mgr.info(f"m{i}", module="m")

            result = mgr.read_sink_tail("mem", 2)
            assert result["success"] is True
            assert result["type"] == "memory"
            assert [r["message"] for r in result["records"]] == ["m2", "m3"]
            assert result["info"]["written"] == 4
        finally:
            mgr.shutdown()

    def test_a_sink_that_stores_nothing_says_so(self, tmp_path) -> None:
        mgr = _manager(
            tmp_path,
            channels={"real": LoggerChannelSchema(type="file", file_path="real.log")},
            scopes={"SYSTEM": LoggerScopeSchema(min_level="INFO", channels=["real"])},
        )
        try:
            result = mgr.read_sink_tail("real")
            assert result["success"] is False
            assert "file" in result["reason"]
        finally:
            mgr.shutdown()

    def test_an_unknown_sink_is_a_named_refusal_not_an_empty_tail(self, tmp_path) -> None:
        """Пустой список на неизвестное имя читался бы как «записей не было»."""
        mgr = _manager(
            tmp_path,
            channels={"mem": LoggerChannelSchema(type="memory", capacity=5)},
            scopes={"SYSTEM": LoggerScopeSchema(min_level="INFO", channels=["mem"])},
        )
        try:
            result = mgr.read_sink_tail("__нет такого__")
            assert result["success"] is False
            assert "records" not in result
        finally:
            mgr.shutdown()
