"""sdk-слой драйвера Modbus — тонкая обёртка над pymodbus + datatypes + errors."""

from Services.modbus.sdk.client import MODBUS_AVAILABLE, ModbusSdkClient
from Services.modbus.sdk.errors import (
    ModbusConnectionError,
    ModbusDriverError,
    ModbusIOError,
    ModbusNotAvailableError,
)

__all__ = [
    "MODBUS_AVAILABLE",
    "ModbusSdkClient",
    "ModbusDriverError",
    "ModbusNotAvailableError",
    "ModbusConnectionError",
    "ModbusIOError",
]
