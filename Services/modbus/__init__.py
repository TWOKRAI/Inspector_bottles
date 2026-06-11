"""modbus — универсальный драйвер Modbus-TCP / RS485 (RTU).

Чистая архитектура (по образцу Services/hikvision_camera):
    sdk/    — тонкая обёртка над pymodbus (graceful import) + datatypes + errors
    core/   — бизнес-логика: ModbusConfig, ModbusDevice (state machine + телеметрия), poller
    plugin/ — плагин для multiprocess_prototype (io-плагин + register-схемы)

Публичный API (экспортируется сразу — работает без фреймворка):
    ModbusDevice, ModbusConfig, TransportType, ConnectionState, ModbusStatus,
    ModbusPoller, RegisterBlock, RegisterKind, ModbusClientProtocol, MODBUS_AVAILABLE

Plugin/Service-слой подтягивается лениво (только при явном импорте):
    from Services.modbus import ModbusPlugin
"""

from Services.modbus.core import (
    ConnectionState,
    DeviceProtocol,
    Field,
    ModbusConfig,
    ModbusDevice,
    ModbusPoller,
    ModbusStatus,
    ProtocolFileError,
    Reg,
    RegBlock,
    RegDW,
    RegisterBlock,
    RegisterKind,
    RegisterMap,
    RegisterMeta,
    TransportType,
    find_protocols,
    load_protocol,
)
from Services.modbus.interfaces import ModbusClientProtocol, RegisterTransport
from Services.modbus.sdk import MODBUS_AVAILABLE, ModbusDriverError

__all__ = [
    "ModbusDevice",
    "ModbusConfig",
    "TransportType",
    "ConnectionState",
    "ModbusStatus",
    "ModbusPoller",
    "RegisterBlock",
    "RegisterKind",
    "RegisterMap",
    "Reg",
    "RegDW",
    "RegBlock",
    "Field",
    "ModbusClientProtocol",
    "RegisterTransport",
    "ModbusDriverError",
    "MODBUS_AVAILABLE",
    # YAML-протоколы устройств
    "load_protocol",
    "find_protocols",
    "DeviceProtocol",
    "RegisterMeta",
    "ProtocolFileError",
]


def __getattr__(name: str):
    """Ленивая загрузка plugin/service-слоя — только при явном импорте."""
    if name == "ModbusPlugin":
        from Services.modbus.plugin.plugin import ModbusPlugin

        return ModbusPlugin
    if name == "ModbusPluginConfig":
        from Services.modbus.plugin.config import ModbusPluginConfig

        return ModbusPluginConfig
    if name == "ModbusRegisters":
        from Services.modbus.plugin.registers import ModbusRegisters

        return ModbusRegisters
    if name == "ModbusService":
        from Services.modbus.service import ModbusService

        return ModbusService
    if name == "ModbusChannel":
        from Services.modbus.channels.modbus_channel import ModbusChannel

        return ModbusChannel
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
