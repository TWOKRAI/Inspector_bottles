"""plugin-слой драйвера Modbus — io-плагин для multiprocess_prototype."""

from Services.modbus.plugin.config import ModbusPluginConfig
from Services.modbus.plugin.plugin import ModbusPlugin
from Services.modbus.plugin.registers import ModbusRegisters

__all__ = ["ModbusPlugin", "ModbusPluginConfig", "ModbusRegisters"]
