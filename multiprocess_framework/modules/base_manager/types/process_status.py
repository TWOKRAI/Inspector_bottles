"""
ProcessStatus — единый enum статусов жизненного цикла процесса.

Объединяет значения из трёх ранее независимых определений (ADR-117):
- process_module/types/types.py (9 значений, str+Enum)
- shared_resources_module/types/types.py (7 значений, Enum)
- process_manager_module/core/process_status.py (класс мониторинга, не enum)

Суперсет всех значений. Базовый класс: str, Enum — для удобной
сериализации (.value всегда str, сравнение с литералами работает).

Импортировать отсюда:
    from multiprocess_framework.modules.base_manager.types import ProcessStatus

Старые пути сохранены как re-export (backward compat).
"""

from enum import Enum


class ProcessStatus(str, Enum):
    """Статусы жизненного цикла процесса (единый enum, ADR-117)."""

    INITIALIZING = "initializing"
    READY = "ready"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"
    CRASHED = "crashed"
    UNRESPONSIVE = "unresponsive"
    FAILED = "failed"
