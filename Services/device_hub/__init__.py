"""device_hub — центральный реестр устройств и менеджер соединений.

Публичный API (импорт без pymodbus НЕ падает):
    DeviceEntry, RegistryStore — реестр
    DeviceManager              — CRUD + lifecycle + dispatch
    build_transport            — фабрика транспортов
    Ошибки: DeviceHubError, DeviceNotFoundError, DeviceBusyError,
            TransportBuildError, RegistryIntegrityError

Драйверы подтягиваются через __init__.py/drivers/ — lazy при необходимости.
"""

from Services.device_hub.errors import (
    DeviceBusyError,
    DeviceHubError,
    DeviceNotFoundError,
    RegistryIntegrityError,
    TransportBuildError,
)
from Services.device_hub.registry.entry import DeviceEntry
from Services.device_hub.registry.store import RegistryStore

__all__ = [
    "DeviceEntry",
    "RegistryStore",
    "DeviceHubError",
    "DeviceNotFoundError",
    "DeviceBusyError",
    "TransportBuildError",
    "RegistryIntegrityError",
]


def __getattr__(name: str):
    """Ленивая загрузка тяжёлых компонентов (тянут framework/modbus)."""
    if name == "DeviceManager":
        from Services.device_hub.manager import DeviceManager

        return DeviceManager
    if name == "build_transport":
        from Services.device_hub.transports import build_transport

        return build_transport
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
