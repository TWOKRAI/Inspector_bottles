"""
stop_budget — окна остановки детей PM из одного числа ``shutdown_timeout`` (Task 1.1, ADR-PMM-035).

Purpose:
    Единственное место формулы бюджета стопа: PM (эскалация детей), спавнер (внешний
    ``join`` PM) и ребёнок (ключ ``stop_budget`` в его конфиге) читают одни и те же числа.
    Раньше формула жила двумя копиями (``process_registry`` и ``spawner.outer_stop_budget``).

Public API (внутренний модуль ``core/``, из ``__init__``/``interfaces`` пакета не экспортируется):
    ``stop_budget(shutdown_timeout) -> dict[str, float]`` и константы окон ниже.

Stability: lite
"""

from __future__ import annotations

import math
from numbers import Real

__all__ = [
    "CHILD_STOP_FRACTION",
    "DEFAULT_SHUTDOWN_TIMEOUT_S",
    "EXIT_SURVIVORS",
    "INFRA_STOP_S",
    "KILL_CONFIRM_S",
    "KILL_RESERVE_S",
    "PM_TEARDOWN_MARGIN_S",
    "SHUTDOWN_TIMEOUT_KEY",
    "STOP_POLL_S",
    "TERMINATE_GRACE_S",
    "stop_budget",
]

# Шаг опроса смерти при остановке группы: задержка реакции, не бюджет.
STOP_POLL_S = 0.05
# Окна эскалации после graceful-срока (ADR-PMM-031): после terminate() — ждать выхода,
# после kill() — ждать подтверждения смерти.
TERMINATE_GRACE_S = 1.0
KILL_CONFIRM_S = 1.0
# Запас внешнего join спавнера сверх внутреннего бюджета PM: teardown самого PM.
PM_TEARDOWN_MARGIN_S = 1.5
# Graceful-бюджет PM, когда ``shutdown_timeout`` не задан (прежнее ``get_config(...) or 5.0``).
DEFAULT_SHUTDOWN_TIMEOUT_S = 5.0
# Потолок сегмента ``infra`` у ребёнка (логгер, телеметрия, очереди после работы).
INFRA_STOP_S = 1.0
# Доля graceful-бюджета PM, которую ребёнок тратит на свой стоп; остаток — запас до terminate().
CHILD_STOP_FRACTION = 0.8
# Резерв эскалации области после её срока: окно terminate + окно подтверждения kill.
KILL_RESERVE_S = TERMINATE_GRACE_S + KILL_CONFIRM_S
# Ключ конфига PM/спавнера с graceful-бюджетом — единственное место строки в коде.
SHUTDOWN_TIMEOUT_KEY = "shutdown_timeout"

#: Код выхода ребёнка, у которого после закрытия корня остались выжившие записи
#: (Task 1.2a, ADR-PMM-036). Занятые коды: 0 (штатно), 1 (исключение), -N (сигнал),
#: 75 (сторож смерти родителя). Монитор читает 76 как `stopped` + событие `survivors`.
EXIT_SURVIVORS = 76


def _graceful_s(shutdown_timeout: object) -> float:
    """Проверить и привести ``shutdown_timeout``; текст ошибки значения не несёт."""
    if shutdown_timeout is None:
        return DEFAULT_SHUTDOWN_TIMEOUT_S
    if isinstance(shutdown_timeout, bool) or not isinstance(shutdown_timeout, Real):
        raise TypeError(f"shutdown_timeout: ожидалось число секунд, получен {type(shutdown_timeout).__name__}")
    value = float(shutdown_timeout)
    if math.isnan(value) or math.isinf(value) or value < 0:
        raise ValueError(
            f"shutdown_timeout ({type(shutdown_timeout).__name__}): нужно конечное неотрицательное число секунд"
        )
    return value or DEFAULT_SHUTDOWN_TIMEOUT_S


def stop_budget(shutdown_timeout: object) -> dict[str, float]:
    """Окна остановки из graceful-бюджета PM.

    ``None``, ``0`` и ``0.0`` — умолчание ``DEFAULT_SHUTDOWN_TIMEOUT_S``. NaN, ±inf и
    отрицательное — ``ValueError``; ``bool`` и нечисловое — ``TypeError``: иначе ошибка
    всплыла бы позже, на открытии области (``_seconds`` в ``lifetime.py``), посреди стопа.

    Ключи строго по порядку: ``work_s``, ``infra_s`` (сегменты ребёнка, сумма
    ``CHILD_STOP_FRACTION * pm_graceful_s``), ``pm_graceful_s`` (graceful-срок PM),
    ``pm_total_s`` (с эскалацией terminate → kill), ``outer_s`` (внешний join спавнера).
    """
    pm_graceful_s = _graceful_s(shutdown_timeout)
    pm_total_s = pm_graceful_s + TERMINATE_GRACE_S + KILL_CONFIRM_S
    outer_s = pm_total_s + PM_TEARDOWN_MARGIN_S
    child_total = CHILD_STOP_FRACTION * pm_graceful_s
    infra_s = min(INFRA_STOP_S, child_total / 4)
    work_s = child_total - infra_s
    return {
        "work_s": work_s,
        "infra_s": infra_s,
        "pm_graceful_s": pm_graceful_s,
        "pm_total_s": pm_total_s,
        "outer_s": outer_s,
    }
