"""manager_setup.py -- Вспомогательные функции для настройки StateStoreManager.

Содержит default throttle-правила и утилиты для bootstrap StateStore.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiprocess_prototype.backend.config.schemas import SystemConfig


# ADR-PM-017 (Task 1.3): центральный троттл — IPC-ПРЕДОХРАНИТЕЛЬ от СБОЙНОГО публикатора,
# а НЕ второй авторитет частоты. Единственный авторитет каденции — publisher-gate процесса
# (per-метрика ``interval_sec`` из ``telemetry.publish``, ADR-PM-016). Поэтому дефолт-правила
# троттла ставятся ЗАВЕДОМО МЯГЧЕ (меньший min-интервал, т.е. пропускают ЧАЩЕ) минимального
# осмысленного интервала публикации: легитимное поднятие частоты через publisher доходит до
# дерева StateStore БЕЗ молчаливого среза (residual #6 закрыт), а троттл срабатывает лишь на
# публикатор, шлющий БЫСТРЕЕ собственной декларации (реальный сбой). Раньше дефолты (1.0с fps
# и др.) совпадали с publisher-дефолтом 1.0с → «поднять частоту» молча гасилось второй
# ступенью (каскад двух плоскостей с равными дефолтами).
_MIN_PUBLISHER_INTERVAL_SEC: float = 0.1  # осмысленный «пол» каденции публикации (10 Гц)
_THROTTLE_SAFETY_MULTIPLIER: float = 0.5  # < 1 → троттл-интервал НИЖЕ пола публикации
# Единый мягкий предохранительный интервал (0.05с ≈ потолок 20 Гц на запись в дерево):
# выше любой легитимной каденции публикации, поэтому её не режет; ограничивает лишь
# runaway-публикатор.
_SAFETY_INTERVAL_SEC: float = _MIN_PUBLISHER_INTERVAL_SEC * _THROTTLE_SAFETY_MULTIPLIER


def _default_throttle_rules() -> dict[str, float]:
    """Дефолт-правила центрального троттла — мягкий IPC-предохранитель (fallback).

    Используются, когда ``sys_config`` не передан или секция ``telemetry.throttle`` в
    ``system.yaml`` не задана владельцем.

    ADR-PM-017 (Task 1.3): все правила ставятся на единый мягкий
    :data:`_SAFETY_INTERVAL_SEC` (заведомо НИЖЕ минимального осмысленного интервала
    публикации) — троттл перестал быть вторым авторитетом частоты и не режет поднятие
    каденции через publisher-gate. Прежние жёсткие дефолты (1.0/2.0/5.0с) молча гасили
    любое поднятие частоты, совпадая с publisher-дефолтом (residual #6). Per-метрика
    каденция теперь — забота publisher-gate; троттл лишь страхует от runaway-публикатора.

    Returns:
        dict вида {glob_pattern: min_interval_sec}.
    """
    interval = _SAFETY_INTERVAL_SEC
    return {
        # Метрики карточки процесса (state.*) — мягкий предохранитель, не авторитет частоты.
        "processes.**.state.fps": interval,
        "processes.**.state.latency_ms": interval,
        "processes.**.state.uptime": interval,
        "processes.**.state.frame_count": interval,
        "processes.**.state.drops": interval,
        # Per-worker метрики — тот же мягкий предохранитель.
        "processes.**.workers.*.effective_hz": interval,
        "processes.**.workers.*.cycle_duration_ms": interval,
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
