"""core-слой драйвера Modbus — бизнес-логика без зависимости от фреймворка."""

from Services.modbus.core.config import ModbusConfig, TransportType
from Services.modbus.core.device import ModbusDevice
from Services.modbus.core.poller import ModbusPoller, RegisterBlock, RegisterKind
from Services.modbus.core.protocol_file import (
    DeviceProtocol,
    ProtocolFileError,
    RegisterMeta,
    find_protocols,
    load_protocol,
)
from Services.modbus.core.register_map import Field, Reg, RegBlock, RegDW, RegisterMap
from Services.modbus.core.status import ConnectionState, ModbusStatus

__all__ = [
    "ModbusConfig",
    "TransportType",
    "ModbusDevice",
    "ModbusPoller",
    "RegisterBlock",
    "RegisterKind",
    "ConnectionState",
    "ModbusStatus",
    "RegisterMap",
    "Reg",
    "RegDW",
    "RegBlock",
    "Field",
    # YAML-протоколы устройств
    "load_protocol",
    "find_protocols",
    "DeviceProtocol",
    "RegisterMeta",
    "ProtocolFileError",
]
