"""Ошибки драйвера Modbus.

Единая иерархия исключений уровня драйвера. Низкоуровневые исключения
pymodbus (ConnectionException, ModbusIOException, ...) перехватываются в
sdk/client.py и оборачиваются в ModbusDriverError, чтобы верхние слои
(core/device, plugin) не зависели от деталей библиотеки.
"""

from __future__ import annotations


class ModbusDriverError(Exception):
    """Базовая ошибка драйвера Modbus."""


class ModbusNotAvailableError(ModbusDriverError):
    """pymodbus не установлен.

    Возникает при попытке реально подключиться без установленной библиотеки.
    Импорт пакета при этом не падает (graceful degradation) — см. MODBUS_AVAILABLE.
    """


class ModbusConnectionError(ModbusDriverError):
    """Не удалось установить или удержать соединение с устройством."""


class ModbusIOError(ModbusDriverError):
    """Ошибка операции чтения/записи (таймаут, exception-ответ устройства)."""
