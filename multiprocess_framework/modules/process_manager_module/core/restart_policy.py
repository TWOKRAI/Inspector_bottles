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
        max_retries: Максимальное число попыток рестарта подряд
        backoff_sec: Задержка перед рестартом (секунды)
        restart_on_crash: Рестартовать при crashed (exitcode != 0)
        restart_on_unresponsive: Рестартовать при отсутствии heartbeat
    """

    enabled: bool = False  # TODO: вернуть True после стабилизации запуска
    max_retries: int = 3
    backoff_sec: float = 2.0
    restart_on_crash: bool = True
    restart_on_unresponsive: bool = True
