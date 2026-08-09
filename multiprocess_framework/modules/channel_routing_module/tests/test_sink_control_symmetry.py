# -*- coding: utf-8 -*-
"""
Тесты Ф0.6 (независимый тестировщик, plans/observability-unified-routing.md):
симметрия control-plane между LoggerManager/ErrorManager/StatsManager на
уровне МЕНЕДЖЕРА (без IPC/BuiltinCommands — та половина в
process_module/tests/test_sink_command_addressing.py).

Тестируется ТОЛЬКО публичный контракт трёх братьев на общей базе
ChannelRoutingManager (Logger/Error/Stats) + характеристика RouterManager
(четвёртый наследник той же базы, но транспорт, не наблюдаемость).
Исходники channel_routing_manager.py / logger_core.py / stats_manager.py
НЕ читались — поведение установлено ЧЁРНЫМ ЯЩИКОМ через публичный API.

Покрывает:
  - Item 1: set_sink_enabled(name, enabled) симметрично на все три менеджера;
            add_tap/remove_tap симметрично на все три менеджера, переживают
            reconfigure(); старые имена add_log_tap/remove_log_tap должны
            исчезнуть без следа (без делегирующих обёрток).
  - Item 3 (половина уровня менеджера): RouterManager сидит на той же общей
    базе — после Item 1 у него технически ТОЖЕ появляется set_sink_enabled.
    Это ожидаемо (не дыра сама по себе): дыру закрывает whitelist на уровне
    IPC-команды (см. test_sink_command_addressing.py::TestManagerWhitelist).
  - Item 5: у StatsManager должен появиться _fallback_log(level, message) —
    симметрично Logger/Error.
"""

from __future__ import annotations

from queue import Queue

import pytest

from multiprocess_framework.modules.error_module.core.error_manager import ErrorManager
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.router_module.channels.queue_channel import QueueChannel
from multiprocess_framework.modules.router_module.core.router_manager import RouterManager
from multiprocess_framework.modules.statistics_module.core.stats_manager import StatsManager


class _CollectSink:
    """Tap-sink: собирает полученные записи (IChannel-совместим)."""

    def __init__(self, name: str = "collect") -> None:
        self._name = name
        self.records: list = []

    @property
    def name(self) -> str:
        return self._name

    def write(self, data: dict) -> dict:
        self.records.append(data)
        return {"status": "success", "channel": self._name}

    def close(self) -> None:
        pass


def _make_logger() -> LoggerManager:
    mgr = LoggerManager(manager_name="SymmetryLogger")
    mgr.initialize()
    return mgr


def _make_error() -> ErrorManager:
    mgr = ErrorManager(config=None)
    mgr.initialize()
    return mgr


def _make_stats() -> StatsManager:
    mgr = StatsManager(manager_name="SymmetryStats", config={"enable_logging": False})
    mgr.initialize()
    return mgr


# (фабрика менеджера, имя РЕАЛЬНОГО дефолтного sink'а — для set_sink_enabled)
MANAGER_CASES = [
    pytest.param(_make_logger, "system_file", id="logger"),
    pytest.param(_make_error, "errors_file", id="error"),
    pytest.param(_make_stats, "file_stats", id="stats"),
]


class TestSetSinkEnabledSymmetry:
    """Item 1: set_sink_enabled(name, enabled) — один и тот же контракт на всех трёх."""

    @pytest.mark.parametrize("make_manager, sink_name", MANAGER_CASES)
    def test_disable_removes_and_enable_recreates(self, make_manager, sink_name) -> None:
        mgr = make_manager()
        try:
            names_before = {ch.name for ch in mgr.get_all_channels()}
            assert sink_name in names_before, f"ожидался дефолтный sink {sink_name!r}"

            assert mgr.set_sink_enabled(sink_name, False) is True
            names_after_disable = {ch.name for ch in mgr.get_all_channels()}
            assert sink_name not in names_after_disable

            assert mgr.set_sink_enabled(sink_name, True) is True
            names_after_enable = {ch.name for ch in mgr.get_all_channels()}
            assert sink_name in names_after_enable
        finally:
            mgr.shutdown()

    @pytest.mark.parametrize("make_manager, sink_name", MANAGER_CASES)
    def test_enable_unknown_name_returns_false(self, make_manager, sink_name) -> None:
        del sink_name
        mgr = make_manager()
        try:
            assert mgr.set_sink_enabled("__nope__", True) is False
        finally:
            mgr.shutdown()

    @pytest.mark.parametrize("make_manager, sink_name", MANAGER_CASES)
    def test_disable_already_disabled_returns_false(self, make_manager, sink_name) -> None:
        mgr = make_manager()
        try:
            assert mgr.set_sink_enabled(sink_name, False) is True
            # Второй disable того же имени: уже не зарегистрирован → False.
            assert mgr.set_sink_enabled(sink_name, False) is False
        finally:
            mgr.shutdown()


class TestTapApiSymmetry:
    """Item 1: add_tap/remove_tap — общий control-plane, старые имена ушли."""

    def test_old_names_gone_on_all_three(self) -> None:
        for mgr in (_make_logger(), _make_error(), _make_stats()):
            try:
                assert hasattr(mgr, "add_log_tap") is False, (
                    f"{type(mgr).__name__}: add_log_tap должен быть удалён "
                    f"(переименован в add_tap) — проект запрещает делегирующие обёртки"
                )
                assert hasattr(mgr, "remove_log_tap") is False, (
                    f"{type(mgr).__name__}: remove_log_tap должен быть удалён"
                )
                assert hasattr(mgr, "add_tap"), f"{type(mgr).__name__}: нет add_tap"
                assert hasattr(mgr, "remove_tap"), f"{type(mgr).__name__}: нет remove_tap"
            finally:
                mgr.shutdown()

    def test_logger_tap_receives_every_record_and_survives_reconfigure(self) -> None:
        mgr = _make_logger()
        try:
            sink = _CollectSink()
            mgr.add_tap(sink, min_level="ERROR")
            mgr.error("boom", module="test")
            mgr.info("noise", module="test")  # ниже порога — не должно попасть
            assert len(sink.records) == 1
            assert sink.records[0]["level"] == "ERROR"

            assert mgr.reconfigure({"default_level": "DEBUG"}) is True
            mgr.error("after-reconfigure", module="test")
            assert len(sink.records) == 2, "tap должен пережить reconfigure()"
        finally:
            mgr.shutdown()

    def test_error_tap_receives_every_record_and_survives_reconfigure(self) -> None:
        mgr = _make_error()
        try:
            sink = _CollectSink()
            mgr.add_tap(sink, min_level="ERROR")
            mgr.error("boom", module="test")
            mgr.warning("below-threshold", module="test")
            assert len(sink.records) == 1
            assert sink.records[0]["level"] == "ERROR"

            assert mgr.reconfigure({}) is True
            mgr.error("after-reconfigure", module="test")
            assert len(sink.records) == 2, "tap должен пережить reconfigure()"
        finally:
            mgr.shutdown()

    def test_stats_tap_receives_every_emitted_metric_record(self) -> None:
        """Item 1 на StatsManager: tap обязан получать КАЖДУЮ запись метрики
        независимо от обычного роутинга по каналам (симметрично Logger/Error).

        НАХОДКА (не ошибка теста): add_tap/remove_tap СТРУКТУРНО присутствуют
        на StatsManager (унаследованы от общей базы) и регистрация подтверждена
        (внутренний _tap_sinks содержит запись с корректным порогом) — но ни
        increment()/gauge()/record_metric(), ни flush() ФАКТИЧЕСКИ не доставляют
        запись в tap-sink (проверено вручную: buffer.total_flushes растёт,
        sink.records остаётся пустым). Это асимметрия с Logger/Error, где тот
        же сценарий (.error() → tap) работает. Если это уже почищено на момент
        прогона — тест зелёный и служит регрессионным стражем; если нет —
        красный по СУЩЕСТВУ (метрики физически не долетают до tap), а не из-за
        ошибки postановки теста (проверено: min_level='DEBUG' — порог не режет,
        flush() реально вызывался — buffer.total_flushes подтверждает).
        """
        mgr = _make_stats()
        try:
            sink = _CollectSink()
            mgr.add_tap(sink, min_level="DEBUG")

            mgr.increment("ops")
            mgr.increment("ops")
            mgr.flush()

            assert len(sink.records) > 0, (
                "StatsManager.add_tap не получает ни одной записи метрики "
                "(increment+flush) — асимметрия с Logger/Error tap"
            )
        finally:
            mgr.shutdown()

    def test_remove_tap_stops_delivery_on_logger_and_error(self) -> None:
        for mgr, emit in (
            (_make_logger(), lambda m: m.error("x", module="test")),
            (_make_error(), lambda m: m.error("x", module="test")),
        ):
            try:
                sink = _CollectSink()
                name = mgr.add_tap(sink, min_level="ERROR")
                assert mgr.remove_tap(name) is True
                emit(mgr)
                assert sink.records == []
                assert mgr.remove_tap(name) is False  # уже нет
            finally:
                mgr.shutdown()


class TestFallbackLogSymmetry:
    """Item 5: last-resort _fallback_log(level, message) — теперь и у StatsManager."""

    def test_stats_manager_has_fallback_log(self) -> None:
        """На момент постановки задачи у StatsManager этого метода не было
        (см. фон задачи) — целевой тест Item 5."""
        mgr = _make_stats()
        try:
            assert hasattr(mgr, "_fallback_log"), (
                "StatsManager должен получить _fallback_log от общей базы, симметрично Logger/Error (item 5)"
            )
            mgr._fallback_log("ERROR", "test-message")  # не должен падать
        finally:
            mgr.shutdown()

    def test_logger_and_error_already_have_fallback_log(self) -> None:
        """Контроль: у Logger/Error оно уже есть — фикс не должен был это сломать."""
        logger = _make_logger()
        error = _make_error()
        try:
            assert hasattr(logger, "_fallback_log")
            assert hasattr(error, "_fallback_log")
        finally:
            logger.shutdown()
            error.shutdown()


class TestRouterManagerSharesBaseButIsNotObservability:
    """Item 3 (половина уровня менеджера).

    RouterManager сидит на той же общей базе, что и Logger/Error/Stats (см.
    фон задачи) — значит после Item 1 у него технически ТОЖЕ появляется
    set_sink_enabled/add_tap. Это НЕ дыра сама по себе: реестр транспортных
    каналов router'а не обязан меняться от одного факта наличия метода на
    общей базе. Полную проверку ОТКАЗА адресации manager="router" через
    IPC-команду (единственную реальную границу безопасности здесь) — см.
    test_sink_command_addressing.py::TestManagerWhitelist (командная половина
    этого пункта).
    """

    def test_router_channel_registry_unaffected_by_symmetric_api_presence(self) -> None:
        router = RouterManager(manager_name="RouterSymmetryProbe")
        router.initialize()
        try:
            q: Queue = Queue()
            router.register_channel(QueueChannel("transport_a", q))
            names_before = {ch.name for ch in router.get_all_channels()}
            assert "transport_a" in names_before

            # Присутствие симметричного API на общей базе — ожидаемо (Item 1).
            assert hasattr(router, "set_sink_enabled"), (
                "RouterManager наследует set_sink_enabled от общей базы после Item 1 "
                "— это ожидаемое следствие общего предка, не отдельная дыра"
            )

            # Но НИКТО его не вызывал — реестр транспортных каналов не тронут.
            names_after = {ch.name for ch in router.get_all_channels()}
            assert names_after == names_before
        finally:
            router.shutdown()
