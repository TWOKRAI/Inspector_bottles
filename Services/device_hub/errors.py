"""Ошибки сервиса device_hub.

Иерархия:
    DeviceHubError            -- базовая
        DeviceNotFoundError   -- устройство не найдено в реестре
        DeviceBusyError       -- устройство занято (draw, connect в процессе)
        TransportBuildError   -- не удалось построить транспорт (bridge-цикл и т.п.)
        RegistryIntegrityError -- нарушение целостности реестра (удаление носителя)
        RegisterTransportUnavailable -- у драйвера нет транспорта регистров (device_read / device_write)
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


class RegisterTransportUnavailable(DeviceHubError):
    """У драйвера нет транспорта регистров (``driver.transport is None``): чтение и запись регистров недоступны.

    Текст постоянный, без входных значений; id устройства — в ``device_id``.
    """

    TEXT = "у устройства нет транспорта регистров"

    def __init__(self, device_id: str = "") -> None:
        super().__init__(self.TEXT)
        self.device_id = device_id
