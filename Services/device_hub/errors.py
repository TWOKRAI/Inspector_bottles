"""Ошибки сервиса device_hub.

Иерархия:
    DeviceHubError            -- базовая
        DeviceNotFoundError   -- устройство не найдено в реестре
        DeviceBusyError       -- устройство занято (draw, connect в процессе)
        TransportBuildError   -- не удалось построить транспорт (bridge-цикл и т.п.)
        RegistryIntegrityError -- нарушение целостности реестра (удаление носителя)
"""

from __future__ import annotations


class DeviceHubError(Exception):
    """Базовая ошибка device_hub."""


class DeviceNotFoundError(DeviceHubError):
    """Устройство не найдено в реестре по id."""


class DeviceBusyError(DeviceHubError):
    """Устройство занято — операция невозможна."""


class TransportBuildError(DeviceHubError):
    """Не удалось построить транспорт для устройства.

    Причины: bridge-цикл, носитель неверного kind, носитель не найден.
    """


class RegistryIntegrityError(DeviceHubError):
    """Нарушение целостности реестра.

    Пример: попытка удалить устройство-носитель при живых bridge-зависимых.
    """
