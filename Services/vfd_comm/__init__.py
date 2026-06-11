"""vfd_comm — сервис устройства «ПЧ INVT GD20», транспорт-агностик.

Клиент зависит только от ``RegisterTransport`` (Services/modbus):
- мост через робота (текущий путь): transport = RobotClient — ПК пишет
  mailbox-регистры робота, Lua ретранслирует на RS-485 и зеркалит статус;
- прямое RTU-подключение (закладка): transport = ModbusDevice(transport=rtu),
  карта DIRECT_MAP.

vfd_comm НЕ импортирует robot_comm — связку (bridge-транспорт через
RobotClient) выполняет DeviceManager в процессе devices.

Graceful degradation: импортируется без pymodbus (VFD_AVAILABLE=False).
"""

from Services.modbus import MODBUS_AVAILABLE as VFD_AVAILABLE

from Services.vfd_comm.core.client import VfdClient
from Services.vfd_comm.core.config import VfdConfig
from Services.vfd_comm.core.datatypes import VFDStatus
from Services.vfd_comm.core.registers import BRIDGE_MAP, DIRECT_MAP
from Services.vfd_comm.errors import VfdBridgeStaleError, VfdCommError, VfdFrequencyError
from Services.vfd_comm.interfaces import VfdClientProtocol

__all__ = [
    "VfdClient",
    "VfdConfig",
    "VFDStatus",
    "VfdClientProtocol",
    "VfdCommError",
    "VfdFrequencyError",
    "VfdBridgeStaleError",
    "BRIDGE_MAP",
    "DIRECT_MAP",
    "VFD_AVAILABLE",
]


def __getattr__(name: str):
    """Ленивая загрузка service-слоя (тянет multiprocess_framework)."""
    if name == "VfdCommService":
        from Services.vfd_comm.service import VfdCommService

        return VfdCommService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
