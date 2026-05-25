"""service_module — реестр и жизненный цикл long-running сервисов.

Публичный API (Phase 3, Task 3.1):
    - IService       — Protocol для структурной совместимости сервисов
    - ServiceLifecycle — enum состояний сервиса (UNREGISTERED/READY/RUNNING/STOPPED/ERROR)
"""

from multiprocess_framework.modules.service_module.interfaces import (
    IService,
    ServiceLifecycle,
)

__all__ = [
    "IService",
    "ServiceLifecycle",
]
