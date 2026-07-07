# -*- coding: utf-8 -*-
"""Контракт health-подсистемы: пути state-дерева и словарь значений.

Это **контракт** (Ф2 Task 2.1): волны C 2.4/2.5 напишут ~30 сайтов
``ctx.health.report_error(...)``, а вкладка «Процессы» / breaker 2.2 / QoS 2.7
будут ЧИТАТЬ здоровье по этим путям. Менять схему потом дорого — поэтому пути
и имена полей зафиксированы здесь как единственный источник истины, а контракт-
тест (``tests/test_health_schema.py``) стережёт их дословно.

Дерево (под корнем процесса ``processes.<name>``)::

    processes.<name>.health.status           # "ok" | "degraded" | "failed"
    processes.<name>.health.errors           # int — счётчик report_error с старта
    processes.<name>.health.last_error        # dict | None (см. LastErrorKey)
    processes.<name>.health.degraded_reason  # str | None — причина деградации
    processes.<name>.health.updated_at        # float — epoch последнего изменения
    processes.<name>.health.breaker          # "closed"|"open"|"half_open" (Task 2.2)

``last_error`` — вложенный dict (Dict at Boundary: pickle-safe, между процессами
идёт как обычное значение)::

    {"type": <класс исключения>, "message": <str(exc)>,
     "context": <сайт-тег>, "ts": <epoch>}
"""

from __future__ import annotations

from enum import Enum

#: Сегмент корня процесса в state-дереве (совпадает с телеметрией
#: ``processes.<name>.state.*`` из ProcessHeartbeat — health живёт рядом).
PROCESSES_ROOT = "processes"
#: Под-сегмент здоровья под корнем процесса.
HEALTH_SEGMENT = "health"


class HealthStatus(str, Enum):
    """Статус здоровья процесса (значение — то, что уходит в state-дерево)."""

    OK = "ok"  # процесс работает штатно
    DEGRADED = "degraded"  # частичная деградация (сосед выпал, breaker open, ...)
    FAILED = "failed"  # процесс нежизнеспособен (give-up супервизора и т.п.)


class HealthField:
    """Имена листьев под ``processes.<name>.health`` (контракт путей)."""

    STATUS = "status"
    ERRORS = "errors"
    LAST_ERROR = "last_error"
    DEGRADED_REASON = "degraded_reason"
    UPDATED_AT = "updated_at"
    BREAKER = "breaker"  # Task 2.2: состояние circuit breaker подряд-ошибок


class LastErrorKey:
    """Ключи вложенного словаря ``last_error`` (контракт значения)."""

    TYPE = "type"
    MESSAGE = "message"
    CONTEXT = "context"
    TS = "ts"


#: Полный, УПОРЯДОЧЕННЫЙ список полей здоровья — итерируется публикатором и
#: сверяется контракт-тестом. Порядок — часть контракта (стабильность дампов).
HEALTH_FIELDS: tuple[str, ...] = (
    HealthField.STATUS,
    HealthField.ERRORS,
    HealthField.LAST_ERROR,
    HealthField.DEGRADED_REASON,
    HealthField.UPDATED_AT,
    HealthField.BREAKER,  # Task 2.2 — аддитивно, в конце (порядок прежних полей неизменен)
)

#: Ключи ``last_error`` — тоже часть контракта.
LAST_ERROR_KEYS: tuple[str, ...] = (
    LastErrorKey.TYPE,
    LastErrorKey.MESSAGE,
    LastErrorKey.CONTEXT,
    LastErrorKey.TS,
)


def health_root(process: str) -> str:
    """Корень поддерева здоровья процесса: ``processes.<process>.health``."""
    return f"{PROCESSES_ROOT}.{process}.{HEALTH_SEGMENT}"


def health_path(process: str, field: str) -> str:
    """Полный путь листа здоровья: ``processes.<process>.health.<field>``."""
    return f"{health_root(process)}.{field}"
