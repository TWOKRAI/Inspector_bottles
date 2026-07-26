# -*- coding: utf-8 -*-
"""
Тесты Ф0.6 (независимый тестировщик, plans/observability-unified-routing.md):
IPC-адресация sink-control по параметру ``manager`` (командная половина).

Контракт (плановое ТЗ Ф0.6, п.2-3):
  - logger.sink.enable / logger.sink.disable принимают параметр ``manager`` со
    значениями "logger" (дефолт, backward-compat) | "error" | "stats";
  - результат называет, какой менеджер был задет (поле "manager");
  - manager="router" — или ЛЮБОЕ значение вне whitelist'а logger|error|stats —
    отклоняется с success=False и причиной, и НЕ должен трогать RouterManager:
    это транспорт (message-канал IPC), а не наблюдаемость (см. фон задачи).

Харнесс — тот же паттерн fake-сервисов, что в существующем
test_observability_commands.py (см. этот файл на предмет стиля): дешёвые
fake-менеджеры вместо реальных Logger/Error/Stats/Router, проверяем только
дисп-логику BuiltinCommands._toggle_logger_sink через её ПУБЛИЧНЫЙ вход —
``command_manager.dispatch(command, data)``.

Половина уровня менеджера (RouterManager с РЕАЛЬНЫМИ каналами) — см.
channel_routing_module/tests/test_sink_control_symmetry.py::
TestRouterManagerSharesBaseButIsNotObservability.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands


class _FakeCommandManager:
    def __init__(self) -> None:
        self.handlers: dict = {}
        self.metadata: dict = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler
        self.metadata[name] = metadata or {}

    def dispatch(self, command: str, data: dict | None = None) -> dict:
        return self.handlers[command](data or {})


class _FakeSinkManager:
    """Fake logger/error/stats — фиксирует вызовы set_sink_enabled(name, enabled)."""

    def __init__(self, sinks=None) -> None:
        self.sink_calls: list = []
        self.sinks: set = set(sinks or {"default_sink"})

    def set_sink_enabled(self, name: str, enabled: bool) -> bool:
        self.sink_calls.append((name, enabled))
        if enabled:
            self.sinks.add(name)
            return True
        if name in self.sinks:
            self.sinks.discard(name)
            return True
        return False


class _FakeRouterManager:
    """RouterManager fake: транспорт, а не наблюдаемость.

    У него, как и у реальных Logger/Error/Stats, ТОЖЕ есть set_sink_enabled
    (общая база, Item 1) — команда sink-control обязана его игнорировать
    ЦЕЛИКОМ, ни разу не вызвав этот метод, независимо от значения ``manager``.
    """

    def __init__(self) -> None:
        self.sink_calls: list = []
        self.channels: set = {"transport_a"}

    def set_sink_enabled(self, name: str, enabled: bool) -> bool:
        self.sink_calls.append((name, enabled))  # НЕ должно случиться
        if enabled:
            self.channels.add(name)
            return True
        if name in self.channels:
            self.channels.discard(name)
            return True
        return False


class _FakeServices:
    def __init__(self, *, logger=None, error=None, stats=None, router=None) -> None:
        self.command_manager = _FakeCommandManager()
        self.logger_manager = logger
        self.error_manager = error
        self.stats_manager = stats
        self.router_manager = router
        self.name = "preprocessor"

    def get_config(self, key, default=None):
        return default

    def _log_info(self, *a, **k) -> None: ...

    def _log_debug(self, *a, **k) -> None: ...


def _make(**kw):
    svc = _FakeServices(**kw)
    bc = BuiltinCommands(svc)
    bc._register_observability_commands()
    return svc, svc.command_manager


class TestManagerAddressing:
    """Item 2: manager=logger|error|stats адресуют РАЗНЫХ менеджеров раздельно."""

    def test_default_manager_is_logger_backward_compat(self) -> None:
        logger = _FakeSinkManager({"errors_file"})
        error = _FakeSinkManager({"errors_file"})
        _svc, cm = _make(logger=logger, error=error)

        res = cm.dispatch("logger.sink.disable", {"sink": "errors_file"})

        assert res["success"] is True
        assert logger.sink_calls == [("errors_file", False)]
        assert error.sink_calls == [], "без явного manager error НЕ должен быть тронут"

    def test_manager_error_addresses_error_manager_only(self) -> None:
        logger = _FakeSinkManager({"errors_file"})
        error = _FakeSinkManager({"errors_file"})
        _svc, cm = _make(logger=logger, error=error)

        res = cm.dispatch("logger.sink.disable", {"sink": "errors_file", "manager": "error"})

        assert res["success"] is True
        assert error.sink_calls == [("errors_file", False)]
        assert logger.sink_calls == [], "manager='error' не должен трогать logger"

    def test_manager_stats_addresses_stats_manager_only(self) -> None:
        stats = _FakeSinkManager({"file_stats"})
        logger = _FakeSinkManager({"file_stats"})
        _svc, cm = _make(logger=logger, stats=stats)

        res = cm.dispatch("logger.sink.disable", {"sink": "file_stats", "manager": "stats"})

        assert res["success"] is True
        assert stats.sink_calls == [("file_stats", False)]
        assert logger.sink_calls == [], "manager='stats' не должен трогать logger"

    def test_result_names_which_manager_was_hit(self) -> None:
        stats = _FakeSinkManager({"file_stats"})
        _svc, cm = _make(stats=stats)

        res = cm.dispatch("logger.sink.enable", {"sink": "file_stats", "manager": "stats"})

        assert res.get("manager") == "stats", "результат обязан называть задетого менеджера"

    def test_enable_then_disable_error_manager_round_trip(self) -> None:
        error = _FakeSinkManager({"errors_file"})
        _svc, cm = _make(error=error)

        off = cm.dispatch("logger.sink.disable", {"sink": "errors_file", "manager": "error"})
        assert off["success"] is True and off["enabled"] is False

        on = cm.dispatch("logger.sink.enable", {"sink": "errors_file", "manager": "error"})
        assert on["success"] is True and on["enabled"] is True

    def test_manager_field_missing_target_is_error(self) -> None:
        """manager='stats' указан, но svc.stats_manager отсутствует (None)."""
        _svc, cm = _make(logger=_FakeSinkManager())
        res = cm.dispatch("logger.sink.disable", {"sink": "x", "manager": "stats"})
        assert res["success"] is False


class TestManagerWhitelist:
    """Item 3 (командная половина): router и любые прочие значения — вне
    периметра адресации. RouterManager не должен быть тронут НИ РАЗУ."""

    def test_manager_router_is_rejected(self) -> None:
        router = _FakeRouterManager()
        _svc, cm = _make(router=router, logger=_FakeSinkManager())

        res = cm.dispatch("logger.sink.disable", {"sink": "transport_a", "manager": "router"})

        assert res["success"] is False
        assert res.get("reason"), "нужна причина отказа"
        assert router.sink_calls == [], "RouterManager НЕ должен быть тронут"
        assert router.channels == {"transport_a"}, "реестр канала router'а не изменился"

    def test_unknown_manager_value_is_rejected(self) -> None:
        router = _FakeRouterManager()
        _svc, cm = _make(router=router, logger=_FakeSinkManager())

        res = cm.dispatch("logger.sink.enable", {"sink": "x", "manager": "totally_bogus"})

        assert res["success"] is False
        assert res.get("reason")
        assert router.sink_calls == []

    def test_router_channels_survive_disable_then_enable_attempt(self) -> None:
        """Полный цикл disable+enable через manager="router" не меняет РЕАЛЬНЫЙ
        (в этом харнессе — fake) канал router'а ни на шаг."""
        router = _FakeRouterManager()
        _svc, cm = _make(router=router)

        res_off = cm.dispatch("logger.sink.disable", {"sink": "transport_a", "manager": "router"})
        res_on = cm.dispatch("logger.sink.enable", {"sink": "transport_a", "manager": "router"})

        assert res_off["success"] is False
        assert res_on["success"] is False
        assert router.channels == {"transport_a"}
        assert router.sink_calls == []

    def test_router_rejected_even_without_router_manager_present(self) -> None:
        """manager='router' отклоняется whitelist'ом ДО обращения к атрибуту —
        не должен падать, даже если svc.router_manager вообще не задан."""
        _svc, cm = _make(logger=_FakeSinkManager())
        res = cm.dispatch("logger.sink.disable", {"sink": "x", "manager": "router"})
        assert res["success"] is False
        assert res.get("reason")
