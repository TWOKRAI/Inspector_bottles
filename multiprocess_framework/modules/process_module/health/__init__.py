# -*- coding: utf-8 -*-
"""health — наблюдаемость отказов процесса (Ф2 Task 2.1).

Публичный API:
- :class:`HealthReporter` — фасад ``ctx.health`` для плагинов;
- :class:`HealthState` — процесс-общий аккумулятор (через :func:`get_or_create_health_state`);
- :func:`publish_health` — публикация в state-дерево (зовёт heartbeat);
- :mod:`.schema` — КОНТРАКТ путей: :func:`health_root`/:func:`health_path`,
  :class:`HealthStatus`, :class:`HealthField`, :data:`HEALTH_FIELDS`.

Контракт путей стережёт ``tests/test_health_schema.py`` — менять дословно опасно
(волны C 2.4/2.5 пишут ~30 сайтов по этим путям).
"""

from __future__ import annotations

from .breaker import (
    DEFAULT_COOLDOWN_SEC,
    DEFAULT_THRESHOLD,
    BreakerState,
    CircuitBreaker,
)
from .schema import (
    HEALTH_FIELDS,
    LAST_ERROR_KEYS,
    HealthField,
    HealthStatus,
    LastErrorKey,
    health_path,
    health_root,
)
from .state import (
    DEFAULT_THROTTLE,
    LOG_ONLY_ENV,
    HealthReporter,
    HealthSelfTestError,
    HealthState,
    IHealthReporter,
    get_or_create_health_state,
    publish_health,
)

__all__ = [
    # contract / schema
    "HealthStatus",
    "HealthField",
    "LastErrorKey",
    "HEALTH_FIELDS",
    "LAST_ERROR_KEYS",
    "health_root",
    "health_path",
    # primitive
    "HealthState",
    "HealthReporter",
    "IHealthReporter",
    "HealthSelfTestError",
    "get_or_create_health_state",
    "publish_health",
    "DEFAULT_THROTTLE",
    "LOG_ONLY_ENV",
    # breaker (Ф2 Task 2.2)
    "CircuitBreaker",
    "BreakerState",
    "DEFAULT_THRESHOLD",
    "DEFAULT_COOLDOWN_SEC",
]
