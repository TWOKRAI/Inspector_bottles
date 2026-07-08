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
    """

    enabled: bool = False  # TODO: вернуть True после стабилизации запуска
    max_retries: int = 3
    backoff_sec: float = 2.0
    window_sec: float = 60.0
    restart_on_crash: bool = True
    restart_on_unresponsive: bool = True
