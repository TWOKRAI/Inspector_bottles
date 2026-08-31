# -*- coding: utf-8 -*-
"""Н-14 сквозь настоящие объекты: инцидент пары не беднее лог-дороги.

Приёмка F1: ``health.report(ERROR)`` даёт ПАРУ записей в плоскости ошибок —
инцидент (через ``HealthState.report_error`` → ``track_error``) и лог-дорогу
(через ``_log_error``). Инцидент приезжал подписчику с ``module="unknown"`` и
пустым контекстом, то есть беднее своего же близнеца.

Корень оказался двойным, и обе половины видны только на сквозном прогоне:

1. штамп источника стоял в ``ObservableMixin._track_error``, а ``HealthState``
   выбирает ПУБЛИЧНЫЙ ``track_error`` (``_resolve_track`` предпочитает его) —
   прокси звал менеджер напрямую, мимо штампа;
2. ``ErrorManager.track_error`` читала из контекста два ключа и выбрасывала
   остальные, поэтому сайт-тег до записи не доезжал.

Харнес — настоящие ``ProcessModule`` + ``LoggerManager`` + ``ErrorManager``,
вход через реальную команду ``health.report``; фейковый только router (граница
процесса). Юниты на каждую половину живут отдельно
(``base_manager/tests/test_source_stamping.py``,
``error_module/tests/test_incident_context.py``) — здесь проверяется, что
вместе они дают ту самую пару, которую мерила приёмка.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import Mock

import pytest

from multiprocess_framework.modules.error_module.core.error_manager import ErrorManager
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule


class _CapturingRouter:
    def __init__(self) -> None:
        self.pushed: List[Dict[str, Any]] = []

    def send_async(self, message: Dict[str, Any], priority: str = "normal") -> None:
        self.pushed.append(message)


def _manager_config(tmp_path, app: str) -> Dict[str, Any]:
    return {
        "app_name": app,
        "log_directory": str(tmp_path),
        "enable_batching": False,
        "modules": {},
        "channels": {"a": {"type": "file", "enabled": True, "file_path": str(tmp_path / f"{app}.log")}},
        "scopes": {
            "SYSTEM": {"channels": ["a"]},
            "BUSINESS": {"channels": ["a"]},
            "DEBUG": {"channels": ["a"]},
        },
    }


@pytest.fixture
def process_with_both_planes(tmp_path):
    logger = LoggerManager(manager_name="PairLog", config=_manager_config(tmp_path, "pair_log"))
    logger.initialize()
    errors = ErrorManager(manager_name="PairErr", config=_manager_config(tmp_path, "pair_err"))
    errors.initialize()

    process = ProcessModule("camera_0")
    router = _CapturingRouter()
    process.router_manager = router
    process.logger_manager = logger
    process.error_manager = errors
    process._observability_hub = Mock()
    # Регистрация в реестре миксина — это и есть путь, по которому появляются
    # публичные прокси (`track_error`), то есть ровно тот, где Н-14 и жила.
    process.register_manager("logger", logger, enabled=True)
    process.register_manager("error", errors, enabled=True)
    try:
        yield process, router
    finally:
        process.unsubscribe_observability_tail(None)
        logger.shutdown()
        errors.shutdown()


def _records(router: _CapturingRouter) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for msg in router.pushed:
        if msg.get("command") != "observability.record":
            continue
        data = msg.get("data") or {}
        for rec in data.get("records", [data]):
            out.append(rec.get("record") or rec)
    return out


def _fire_health_report(process: ProcessModule) -> dict:
    bc = BuiltinCommands.__new__(BuiltinCommands)
    bc._services = process
    return bc._cmd_health_report({"context": "grab_frame", "message": "камера отвалилась", "level": "ERROR"})


class TestIncidentPair:
    def test_incident_names_its_source_instead_of_unknown(self, process_with_both_planes):
        """Заявленное свойство 1.4: ни одна запись пары не приезжает «ничьей».

        Живой замер приёмки F1 до правки: инцидент нёс ``module="unknown"``
        при близнеце с ``module="diagnostics"``.
        """
        process, router = process_with_both_planes
        assert process.subscribe_observability_tail("probe", "INFO")["success"] is True

        assert _fire_health_report(process)["success"] is True

        records = _records(router)
        assert records, "пара не доехала до подписчика вовсе"
        modules = [r.get("module") for r in records]
        assert "unknown" not in modules, f"инцидент по-прежнему ничей: {modules}"

    def test_incident_carries_the_site_tag_in_its_context(self, process_with_both_planes):
        """Сайт-тег ``health.report(context=…)`` — поле записи, а не только текст."""
        process, router = process_with_both_planes
        process.subscribe_observability_tail("probe", "INFO")

        _fire_health_report(process)

        contexts = [(r.get("extra") or {}).get("context") or {} for r in _records(router)]
        assert any(c.get("context") == "grab_frame" for c in contexts), (
            f"сайт-тег не доехал ни в одной записи пары: {contexts}"
        )

    def test_the_pair_is_two_records_in_the_errors_plane(self, process_with_both_planes):
        """Форма пары не изменилась: инцидент + лог-дорога, обе ERROR.

        Без этой рамки «module не unknown» доказывалось бы и записью, которой
        вообще нет: пустой список тоже не содержит «unknown».
        """
        process, router = process_with_both_planes
        process.subscribe_observability_tail("probe", "INFO")

        _fire_health_report(process)

        errors_plane = [r for r in _records(router) if r.get("severity") == "error"]
        assert len(errors_plane) == 2, f"пара распалась: {[r.get('message') for r in _records(router)]}"
