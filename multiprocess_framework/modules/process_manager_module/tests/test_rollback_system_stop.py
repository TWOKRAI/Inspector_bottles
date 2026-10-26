# -*- coding: utf-8 -*-
"""Task 1.9b (ревью р.2, Р2-1) — условия отката ``_rollback_to_snapshot`` при неподтверждённой остановке.

Голый PM (``conftest.make_pm``), реестр с ``stop_many -> {x: False, y: True}``; откат вызван напрямую.
Наблюдаем действия, а не вызовы приватных имён: строки лога PM (ERROR/WARNING), записи состояния
``system.switch.unstoppable`` (alert, B-3), создание процессов в реестре (шов ``create_and_register``) и
регистрация в ``SharedResourcesManager`` (шов ``register_process`` — provision), запуск процесса
(``MockProcess.start``).
Ожидаемые значения — литералы. Тест привязывает обе половины ADR-PMM-039 D4 для отката:
(i) без системного стопа — ERROR и alert как прежде, ``y`` пересоздаётся, ``x`` нет;
(ii) при ``system_stop_event`` — один WARNING, 0 ERROR, 0 alert, ни provision, ни create, ни start даже для ``y``.
"""

from __future__ import annotations

import threading
from typing import Any

from .conftest import make_pm

ALERT_PATH = "system.switch.unstoppable"
SNAPSHOT = {"x": {"class": "m.X"}, "y": {"class": "m.Y"}}


def _prepared_pm() -> tuple[Any, dict[str, list]]:
    pm = make_pm(SNAPSHOT)
    seen: dict[str, list] = {"created": [], "registered": [], "alerts": []}

    registry = pm._process_registry
    registry.stop_many = lambda names, timeout=5.0, **kw: {n: n != "x" for n in names}
    original_create = registry.create_and_register

    def create_and_register(name: str, *args: Any, **kwargs: Any) -> Any:
        seen["created"].append(name)
        return original_create(name, *args, **kwargs)

    registry.create_and_register = create_and_register

    shared = pm.shared_resources
    original_register = shared.register_process

    def register_process(name: str, *args: Any, **kwargs: Any) -> Any:
        seen["registered"].append(name)
        return original_register(name, *args, **kwargs)

    shared.register_process = register_process

    def state_op(op: str, payload: dict, *args: Any, **kwargs: Any) -> None:
        if op == "handle_state_set" and payload.get("path") == ALERT_PATH:
            seen["alerts"].append(list(payload["value"]))

    pm._state_op = state_op
    return pm, seen


def _lines(pm: Any, level: str) -> list[str]:
    return [str(call.args[0]) for call in getattr(pm, f"_log_{level}").call_args_list]


def test_rollback_without_system_stop_logs_error_alerts_and_recreates_only_confirmed() -> None:
    """(i) ``_pm_stopping()`` ложно: ERROR «НЕ подтверждена для ['x']», alert ``['x']`` ровно один раз; ``y`` пересоздан
    (provision, create, start), ``x`` — нет."""
    pm, seen = _prepared_pm()
    assert pm._pm_stopping() is False

    pm._rollback_to_snapshot(SNAPSHOT, None, None)

    errors = [line for line in _lines(pm, "error") if "НЕ подтверждена" in line]
    assert len(errors) == 1 and "['x']" in errors[0], errors
    assert seen["alerts"] == [["x"]], seen["alerts"]
    assert seen["created"] == ["y"], seen["created"]
    assert seen["registered"] == ["y"], seen["registered"]
    assert pm._process_registry.get_process_by_name("y")._started is True
    assert not [line for line in _lines(pm, "warning") if "системный стоп" in line]


def test_rollback_under_system_stop_one_warning_no_error_no_alert_no_recreation() -> None:
    """(ii) ``_system_stop_event`` взведён: ровно один WARNING, 0 ERROR, 0 alert; provision, create и start не идут,
    даже для ``y`` (остановка которого подтверждена)."""
    pm, seen = _prepared_pm()
    pm._system_stop_event = threading.Event()
    pm._system_stop_event.set()
    assert pm._pm_stopping() is True

    pm._rollback_to_snapshot(SNAPSHOT, None, None)

    warnings = [line for line in _lines(pm, "warning") if "системный стоп" in line]
    assert len(warnings) == 1 and "['x']" in warnings[0], warnings
    assert _lines(pm, "error") == [], _lines(pm, "error")
    assert seen["alerts"] == [], seen["alerts"]
    assert seen["created"] == [], seen["created"]
    assert seen["registered"] == [], seen["registered"]
