# -*- coding: utf-8 -*-
"""Task 0.5c (c6): секция ``introspect.observability.forwarders``.

Значение подписчика — сумма счётчиков СОЗДАННЫХ проводкой каналов: batch всегда,
error-tap и logger-tap — только при менеджере с ``add_tap``. Счётчики к секции
доставляет сама проводка: атрибут ``counters_snapshot`` на замыкании ``forwarder``.
Форвардер без атрибута или с бросающим атрибутом — запись ``{"error": <класс>}``,
секция и команда не падают.

Функция секции берётся через модуль, а не импортом имени: до c6 её нет, и тест
краснеет сам (``AttributeError``), а не роняет сбор всего файла.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.managers import observability_wiring as wiring
from multiprocess_framework.modules.process_module.managers.observability_wiring import (
    unwire_observability_forward,
    wire_observability_forward,
)


class _SuccessRouter:
    """Роутер-заглушка: ``send`` принимает всё; ``send_async`` пишет в тот же журнал."""

    def __init__(self) -> None:
        self.sent: List[Dict[str, Any]] = []

    def send_async(self, message: Dict[str, Any], priority: str = "normal") -> None:
        self.sent.append(message)

    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        self.sent.append(message)
        return {"status": "success"}


def _hub_record(message: str) -> Dict[str, Any]:
    return {"kind": "log", "module": "cam0", "ts": 1.0, "severity": "info", "message": message}


def _logger(name: str, tmp_path) -> LoggerManager:
    directory = tmp_path / name
    directory.mkdir()
    return LoggerManager(manager_name=name, config={"log_directory": str(directory)})


def test_forwarders_section_sums_created_channels(tmp_path) -> None:
    """Настоящая проводка и два настоящих менеджера: секция = batch + error-tap + logger-tap."""
    router = _SuccessRouter()
    error_mgr = _logger("fpr-error", tmp_path)
    logger_mgr = _logger("fpr-logger", tmp_path)
    forwarder, taps = wire_observability_forward(
        router, "gui", "cam0", logger_manager=logger_mgr, error_manager=error_mgr
    )
    try:
        forwarder([_hub_record("a"), _hub_record("b")])  # batch: 1 пуш, 2 записи
        logger_mgr.error("boom-logger", module="cam0")  # logger-tap: 1 пуш, 1 запись
        error_mgr.error("boom-error", module="cam0")  # error-tap: 1 пуш, 1 запись
        svc = SimpleNamespace(_observability_forwarders={"gui": (forwarder, taps)})
        report = wiring.forwarders_plane_report(svc)
    finally:
        unwire_observability_forward(taps)
        logger_mgr.shutdown()
        error_mgr.shutdown()

    assert len(router.sent) == 3
    assert report == {"forwarders": {"gui": {"sent": 4, "messages": 3, "dropped": 0, "send_failed": 0}}}


class _Services:
    """Носитель менеджеров для настоящей ``_cmd_introspect_observability``."""

    def __init__(self, logger: Any, forwarders: Dict[str, Any]) -> None:
        self.logger_manager = logger
        self.error_manager = None
        self.stats_manager = None
        self.router_manager = None
        self.command_manager = None
        self.name = "cam0"
        self._observability_forwarders = forwarders

    def get_config(self, key, default=None):
        return default

    def _log_info(self, *a, **k) -> None: ...

    def _log_debug(self, *a, **k) -> None: ...


def test_introspect_observability_returns_forwarders(tmp_path) -> None:
    """Сквозной: команда ``introspect.observability`` отдаёт секцию ``forwarders``."""
    from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands

    router = _SuccessRouter()
    logger_mgr = _logger("fpr-cmd", tmp_path)
    forwarder, taps = wire_observability_forward(router, "gui", "cam0", logger_manager=logger_mgr)
    try:
        forwarder([_hub_record("a")])  # batch: 1 пуш, 1 запись
        logger_mgr.error("boom", module="cam0")  # logger-tap: 1 пуш, 1 запись
        result = BuiltinCommands(_Services(logger_mgr, {"gui": (forwarder, taps)}))._cmd_introspect_observability(None)
    finally:
        unwire_observability_forward(taps)
        logger_mgr.shutdown()

    assert result["success"] is True
    assert result["forwarders"] == {"gui": {"sent": 2, "messages": 2, "dropped": 0, "send_failed": 0}}


class _BrokenForwarder:
    """Форвардер, чей ``counters_snapshot`` бросает; текст исключения — «входное значение»."""

    def __call__(self, records: List[dict]) -> None:
        return None

    def counters_snapshot(self) -> Dict[str, int]:
        raise RuntimeError("counters broken: secret-payload")


def test_forwarders_entry_degrades_without_counters() -> None:
    """Нет ``counters_snapshot`` или он бросил: запись подписчика — ``{"error": <класс>}``."""

    def bare_forwarder(records: List[dict]) -> None:
        return None

    svc = SimpleNamespace(_observability_forwarders={"bare": (bare_forwarder, []), "broken": (_BrokenForwarder(), [])})

    report = wiring.forwarders_plane_report(svc)

    assert report == {"forwarders": {"bare": {"error": "AttributeError"}, "broken": {"error": "RuntimeError"}}}
    assert wiring.forwarders_plane_report(SimpleNamespace(_observability_forwarders={})) == {"forwarders": {}}
    assert wiring.forwarders_plane_report(SimpleNamespace()) == {"forwarders": {}}
