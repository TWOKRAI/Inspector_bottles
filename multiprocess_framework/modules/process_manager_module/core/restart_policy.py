"""
RestartPolicy — политика автоматического перезапуска процессов.

Используется ProcessMonitor для принятия решения о рестарте
упавших (crashed) или зависших (unresponsive) процессов.
"""

from __future__ import annotations

from ...data_schema_module import SchemaBase


class RestartPolicy(SchemaBase):
    """Политика авто-рестарта процессов.

    Attributes:
        enabled: Включён ли авто-рестарт
        max_retries: Максимальное число попыток рестарта В ОКНЕ window_sec
        backoff_sec: Задержка перед рестартом (секунды)
        window_sec: Окно стабильности (секунды) для подсчёта попыток. Метки
            рестартов старше ``now - window_sec`` протухают и не считаются —
            это защищает от вечной flap-петли (пожизненный счётчик сдавался
            навсегда), одновременно давая процессу «отдышаться». ``0`` →
            пожизненный счётчик как раньше (метки не протухают).
        restart_on_crash: Рестартовать при crashed (exitcode != 0)
        restart_on_unresponsive: Рестартовать при отсутствии heartbeat
        restart_on_health_failed: Рестартовать живой (heartbeating) процесс, который
            САМ выставил ``health.status=failed`` (тихо-мёртвый: liveness ОК, но
            плагин/breaker объявил фатальный отказ). H4 (Ф4-добор). Срабатывает
            только при включённом env-флаге ``FW_HEALTH_RESTART`` (default off) —
            liveness-рестарт (crash/unresponsive) от этого флага не зависит.
    """

    # Raw-дефолт enabled=False — безопасный «нейтральный» для прямого
    # RestartPolicy() в тестах/минимальных конфигах. В проде композиция ставит
    # enabled=True per-process через FW_AUTORESTART (авто-рестарт-всех, Ф4) —
    # см. process_manager_process._resolve_policy. Т.е. дефолт off, прод on.
    enabled: bool = False
    max_retries: int = 3
    backoff_sec: float = 2.0
    window_sec: float = 60.0
    restart_on_crash: bool = True
    restart_on_unresponsive: bool = True
    restart_on_health_failed: bool = True
