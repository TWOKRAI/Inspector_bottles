"""manager_setup.py -- Вспомогательные функции для настройки StateStoreManager.

Содержит default throttle-правила и утилиты для bootstrap StateStore.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiprocess_prototype.backend.config.schemas import SystemConfig


def _default_throttle_rules() -> dict[str, float]:
    """Хардкод-дефолты центрального троттла (fallback).

    Используются, когда ``sys_config`` не передан или секция
    ``telemetry.throttle`` в ``system.yaml`` не задана владельцем —
    обратная совместимость с поведением до PC 2.1
    (`plans/telemetry-publish-control.md`, Фаза 2).

    Returns:
        dict вида {glob_pattern: min_interval_sec}.
    """
    return {
        # fps -- максимум 1 обновление в секунду
        "processes.**.state.fps": 1.0,
        # latency процесса -- максимум 1 обновление в секунду
        "processes.**.state.latency_ms": 1.0,
        # uptime процесса -- максимум 1 обновление в секунду
        "processes.**.state.uptime": 1.0,
        # frame_count -- максимум 1 обновление в 2 секунды
        "processes.**.state.frame_count": 2.0,
        # drops -- максимум 1 обновление в 5 секунд (редкая метрика)
        "processes.**.state.drops": 5.0,
        # частота воркера -- максимум 1 обновление в секунду
        "processes.**.workers.*.effective_hz": 1.0,
        # длительность цикла воркера -- максимум 1 обновление в секунду
        "processes.**.workers.*.cycle_duration_ms": 1.0,
        # Статусы (state.status, workers.*.status) НЕ троттлятся — должны быть
        # отзывчивыми на старт/стоп; публикуются только при изменении.
    }


def build_throttle_rules(sys_config: "SystemConfig | None" = None) -> dict[str, float]:
    """Собрать throttle-правила для центрального троттла StateStoreManager.

    Правила ограничивают частоту обновлений высокочастотных метрик,
    чтобы не перегружать StateStore и IPC (вторая плоскость плана
    `plans/telemetry-publish-control.md` — IPC-страховка поверх publisher-gate
    из Фазы 1; сами правила применяет ``ThrottleMiddleware``, PC 0.1).

    Источник — ``sys_config.telemetry.throttle`` (секция ``telemetry.throttle``
    в ``system.yaml``). Решение по совмещению с дефолтами (PC 2.1): заданный
    ``throttle`` ПОЛНОСТЬЮ ЗАМЕНЯЕТ хардкод-дефолты, а не мержится поверх них —
    задав хотя бы одно правило, владелец берёт на себя весь список осознанно
    (явный контроль вместо скрытого слияния с умолчаниями). Пустой или
    отсутствующий ``sys_config``/``throttle`` — прежние хардкод-дефолты
    (обратная совместимость: поведение без конфига не меняется).

    Args:
        sys_config: валидированный ``SystemConfig`` (``None`` — использовать
            дефолты; так же, как при пустом ``sys_config.telemetry.throttle``).

    Returns:
        dict вида {glob_pattern: min_interval_sec}.
    """
    throttle = sys_config.telemetry.throttle if sys_config is not None else None
    if not throttle:
        return _default_throttle_rules()
    return dict(throttle)
