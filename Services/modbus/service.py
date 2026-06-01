"""ModbusService — обёртка драйвера Modbus для ServiceRegistry.

Реализует контракт IService (start/stop/get_status) поверх core.ModbusDevice.
В отличие от плагина (живёт внутри процесса pipeline), сервис — это long-running
ресурс, управляемый из вкладки «Сервисы»: lifecycle и сводный статус наружу.

Discovery: ServiceRegistry.scanner находит этот файл по имени ``service.py`` и
импортирует — декоратор @register_service регистрирует сервис автоматически.
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.service_module import IService, register_service

from Services.modbus.core.config import ModbusConfig
from Services.modbus.core.device import ModbusDevice


@register_service(name="modbus")
class ModbusService:
    """Сервис драйвера Modbus-TCP / RS485.

    Атрибуты:
        name   — идентификатор сервиса для ServiceRegistry.
        status — текущее состояние ("stopped" | "running" | "error").
    """

    name: str = "modbus"

    def __init__(self) -> None:
        self.status: str = "stopped"
        self._device: ModbusDevice | None = None

    # ------------------------------------------------------------------ #
    # Публичный API (IService-совместимый)
    # ------------------------------------------------------------------ #

    def start(self, config: dict) -> bool:
        """Создать устройство из config-словаря и подключиться.

        Args:
            config: параметры подключения (transport, host, port, unit_id, ...).

        Returns:
            True при успешном подключении.
        """
        cfg = ModbusConfig.from_dict(config or {})
        self._device = ModbusDevice(cfg)
        ok = self._device.connect()
        self.status = "running" if ok else "error"
        return ok

    def stop(self) -> bool:
        """Отключиться и освободить устройство."""
        if self._device is not None:
            self._device.disconnect()
            self._device = None
        self.status = "stopped"
        return True

    def get_status(self) -> dict:
        """Вернуть сводный статус сервиса (state + телеметрия устройства)."""
        data: dict[str, Any] = {"state": self.status, "service": self.name}
        if self._device is not None:
            data["device"] = self._device.get_status()
        return data

    def __repr__(self) -> str:
        return f"ModbusService(status={self.status!r})"


# Явная проверка структурной совместимости (runtime, не ABC)
assert isinstance(ModbusService(), IService), "ModbusService не удовлетворяет IService Protocol"
