# -*- coding: utf-8 -*-
"""RED (независимый тестер, plans/observability-closure): «один разъём на точку».

Критерий приёмки 2 (см. бриф задачи): ``health.report`` даёт РОВНО ОДНУ строку
в персистентном сторе (``ObservabilityStore``) на один инцидент. Сегодня — три
(команда с ``level="ERROR"`` даёт: WARNING-строку ``[health]`` из
``HealthState._safe_log``, ERROR-строку из track-пути через ``ErrorManager.track_error``
-> ``log_exception`` -> ``self.error(...)``, и ЕЩЁ одну ERROR-строку — явный
``_log_error("[health.report] ...")``, который команда зовёт САМА при ``level=ERROR``,
см. ``builtin_commands.py::_cmd_health_report``).

Источник истины — ``interface.py`` для этого механизма НЕ существует
(MODULE_CONTRACT: impl-only). Прежнее принятое поведение «пара из двух ERROR-записей»
зафиксировано соседним ``test_incident_pair_carries_source.py::test_the_pair_is_two_records_in_the_errors_plane``
(её харнес переиспользован здесь один-в-один) — эта задача явно ТРЕБУЕТ его
пересмотреть в сторону одной строки; переписывать/удалять чужой существующий тест
не входит в мою роль (я тестов реализации не трогаю), поэтому здесь — отдельный
файл с новым целевым контрактом.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List
from unittest.mock import Mock

from multiprocess_framework.modules.error_module.core.error_manager import ErrorManager
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule
from multiprocess_framework.modules.process_module.managers.observability_wiring import (
    unwire_observability_store,
    wire_observability_store,
)


class _CapturingRouter:
    def send_async(self, message: Dict[str, Any], priority: str = "normal") -> None:
        return None


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


def _fire_health_report(process: ProcessModule) -> dict:
    bc = BuiltinCommands.__new__(BuiltinCommands)
    bc._services = process
    return bc._cmd_health_report({"context": "grab_frame", "message": "камера отвалилась", "level": "ERROR"})


def _dump(rows: List[Dict[str, Any]]) -> str:
    return "\n".join(
        f"  #{r.get('id')} kind={r.get('kind')} severity={r.get('severity')} msg={r.get('message')!r}" for r in rows
    )


class TestHealthReportIsOneIncidentOneRow:
    def test_health_report_with_level_error_produces_exactly_one_store_row(self, tmp_path) -> None:
        logger = LoggerManager(manager_name="OneRowLog", config=_manager_config(tmp_path, "one_row_log"))
        logger.initialize()
        errors = ErrorManager(manager_name="OneRowErr", config=_manager_config(tmp_path, "one_row_err"))
        errors.initialize()

        process = ProcessModule("camera_0")
        process.router_manager = _CapturingRouter()
        process.logger_manager = logger
        process.error_manager = errors
        process._observability_hub = Mock()
        process.register_manager("logger", logger, enabled=True)
        process.register_manager("error", errors, enabled=True)

        store, taps = wire_observability_store(
            error_manager=errors,
            logger_manager=logger,
            db_path=str(tmp_path / "store.db"),
            process="camera_0",
            min_level="INFO",
        )
        try:
            ts_before = time.time()
            result = _fire_health_report(process)
            assert result["success"] is True, result

            rows = store.list_records(process="camera_0", since=ts_before - 1.0, limit=50)
            assert len(rows) == 1, (
                f"health.report(level=ERROR) обязан дать РОВНО одну строку в сторе на один "
                f"инцидент, получено {len(rows)}:\n{_dump(rows)}"
            )
            assert rows[0]["kind"] == "error", f"единственная строка обязана быть kind=error: {rows[0]}"
        finally:
            unwire_observability_store(store, taps)
            logger.shutdown()
            errors.shutdown()
