"""service_module — реестр и жизненный цикл long-running сервисов.

Публичный API:
    - IService         — Protocol для структурной совместимости сервисов
    - ServiceLifecycle  — enum состояний (UNREGISTERED/READY/RUNNING/STOPPED/ERROR)
    - ServiceEntry      — dataclass-запись в реестре (name, cls, lifecycle, meta)
    - ServiceRegistry   — singleton-реестр сервисов (thread-safe)
    - register_service  — декоратор для автоматической регистрации класса
    - discover          — сканирование директорий и авторегистрация сервисов
    - DiscoveryResult   — результат сканирования (loaded / failed / total)
"""

from multiprocess_framework.modules.service_module.interfaces import (
    IService,
    ServiceLifecycle,
)
from multiprocess_framework.modules.service_module.registry import (
    ServiceEntry,
    ServiceRegistry,
    register_service,
)
from multiprocess_framework.modules.service_module.scanner import (
    DiscoveryResult,
    discover,
)

__all__ = [
    "DiscoveryResult",
    "IService",
    "ServiceEntry",
    "ServiceLifecycle",
    "ServiceRegistry",
    "discover",
    "register_service",
]
