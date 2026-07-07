# -*- coding: utf-8 -*-
"""Контракт-тест health-схемы (Ф2 Task 2.1).

Стережёт пути state-дерева и имена полей ДОСЛОВНО: волны C 2.4/2.5 напишут ~30
сайтов по этим путям, а вкладка «Процессы» / breaker 2.2 будут по ним читать.
Любая правка констант ломает этот тест намеренно — это дорогая, осознанная смена
контракта, а не случайный дрейф.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.health import (
    HEALTH_FIELDS,
    LAST_ERROR_KEYS,
    HealthField,
    HealthStatus,
    LastErrorKey,
    health_path,
    health_root,
)


def test_health_root_is_frozen() -> None:
    assert health_root("cam0") == "processes.cam0.health"
    assert health_root("ProcessManager") == "processes.ProcessManager.health"


def test_health_path_is_frozen() -> None:
    assert health_path("cam0", HealthField.STATUS) == "processes.cam0.health.status"
    assert health_path("cam0", HealthField.ERRORS) == "processes.cam0.health.errors"
    assert health_path("cam0", HealthField.LAST_ERROR) == "processes.cam0.health.last_error"
    assert health_path("cam0", HealthField.DEGRADED_REASON) == "processes.cam0.health.degraded_reason"
    assert health_path("cam0", HealthField.UPDATED_AT) == "processes.cam0.health.updated_at"
    assert health_path("cam0", HealthField.BREAKER) == "processes.cam0.health.breaker"


def test_health_fields_exact_set_and_order() -> None:
    # Порядок — часть контракта (стабильность публикации/дампов).
    # Task 2.2: поле "breaker" добавлено АДДИТИВНО в конец — порядок прежних пяти
    # полей неизменен (волны C 2.4/2.5 читают их по стабильным индексам/путям).
    assert HEALTH_FIELDS == (
        "status",
        "errors",
        "last_error",
        "degraded_reason",
        "updated_at",
        "breaker",
    )


def test_health_status_values() -> None:
    assert HealthStatus.OK.value == "ok"
    assert HealthStatus.DEGRADED.value == "degraded"
    assert HealthStatus.FAILED.value == "failed"
    assert {s.value for s in HealthStatus} == {"ok", "degraded", "failed"}


def test_last_error_keys_frozen() -> None:
    assert LAST_ERROR_KEYS == ("type", "message", "context", "ts")
    assert LastErrorKey.TYPE == "type"
    assert LastErrorKey.MESSAGE == "message"
    assert LastErrorKey.CONTEXT == "context"
    assert LastErrorKey.TS == "ts"


def test_health_field_names_match_fields_tuple() -> None:
    # HealthField-константы и HEALTH_FIELDS не должны расходиться.
    assert set(HEALTH_FIELDS) == {
        HealthField.STATUS,
        HealthField.ERRORS,
        HealthField.LAST_ERROR,
        HealthField.DEGRADED_REASON,
        HealthField.UPDATED_AT,
        HealthField.BREAKER,
    }
