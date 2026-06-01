"""Тонкая обёртка над pymodbus (sync-клиент), транспорт-агностичная.

Назначение слоя ``sdk``:
- изолировать остальной код от деталей pymodbus (имена аргументов, типы ответов);
- graceful degradation — пакет импортируется даже без установленной pymodbus
  (``MODBUS_AVAILABLE = False``), реальная ошибка возникает только при connect();
- единый перевод низкоуровневых исключений pymodbus в ModbusDriverError.

Совместимость версий: в pymodbus 3.7+ адрес ведомого передаётся как ``device_id=``,
в более ранних 3.x — как ``slave=``/``unit=``. Обёртка пробует ``device_id`` и при
``TypeError`` откатывается на ``slave``.
"""

from __future__ import annotations

from typing import Any

from Services.modbus.core.config import ModbusConfig, TransportType
from Services.modbus.sdk.errors import (
    ModbusConnectionError,
    ModbusIOError,
    ModbusNotAvailableError,
)

# --------------------------------------------------------------------------- #
# Graceful import pymodbus
# --------------------------------------------------------------------------- #
try:
    from pymodbus.client import ModbusSerialClient, ModbusTcpClient  # type: ignore
    from pymodbus.exceptions import ModbusException  # type: ignore

    MODBUS_AVAILABLE = True
except ImportError:  # pragma: no cover - окружение без pymodbus
    ModbusTcpClient = None  # type: ignore
    ModbusSerialClient = None  # type: ignore
    ModbusException = Exception  # type: ignore
    MODBUS_AVAILABLE = False


class ModbusSdkClient:
    """Обёртка над sync-клиентом pymodbus.

    Создаёт нужный транспорт (TCP/RTU) из ModbusConfig и предоставляет
    единообразные методы чтения/записи, возвращающие чистые list[int]/list[bool].
    Не thread-safe сам по себе — синхронизацию обеспечивает ModbusDevice.
    """

    def __init__(self, config: ModbusConfig) -> None:
        self._cfg = config
        self._client: Any | None = None

    # ------------------------------------------------------------------ #
    # Управление соединением
    # ------------------------------------------------------------------ #

    def _build_client(self) -> Any:
        """Сконструировать pymodbus-клиент по конфигу."""
        if not MODBUS_AVAILABLE:
            raise ModbusNotAvailableError("pymodbus не установлен — установите extra: pip install '.[modbus]'")
        cfg = self._cfg
        if cfg.transport is TransportType.TCP:
            return ModbusTcpClient(
                host=cfg.host,
                port=cfg.port,
                timeout=cfg.timeout_sec,
                retries=cfg.retries,
            )
        return ModbusSerialClient(
            port=cfg.serial_port,
            baudrate=cfg.baudrate,
            parity=cfg.parity,
            stopbits=cfg.stopbits,
            bytesize=cfg.bytesize,
            timeout=cfg.timeout_sec,
            retries=cfg.retries,
        )

    def connect(self) -> bool:
        """Установить соединение. Бросает ModbusConnectionError при неудаче."""
        if self._client is None:
            self._client = self._build_client()
        try:
            ok = bool(self._client.connect())
        except ModbusException as exc:  # pragma: no cover - сетевые сбои
            raise ModbusConnectionError(str(exc)) from exc
        if not ok:
            raise ModbusConnectionError(f"Не удалось подключиться к {self._cfg.describe()}")
        return True

    def close(self) -> None:
        """Закрыть соединение (идемпотентно)."""
        if self._client is not None:
            try:
                self._client.close()
            finally:
                self._client = None

    @property
    def connected(self) -> bool:
        """Состояние соединения по данным pymodbus."""
        return bool(self._client is not None and getattr(self._client, "connected", False))

    # ------------------------------------------------------------------ #
    # Низкоуровневый вызов с откатом device_id -> slave
    # ------------------------------------------------------------------ #

    def _call(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Вызвать метод клиента, подставив адрес ведомого совместимым способом."""
        if self._client is None:
            raise ModbusConnectionError("Клиент не подключён")
        method = getattr(self._client, method_name)
        unit = self._cfg.unit_id
        try:
            result = method(*args, device_id=unit, **kwargs)
        except TypeError:
            # Старые версии pymodbus: device_id отсутствует -> slave
            result = method(*args, slave=unit, **kwargs)
        if result is None or result.isError():
            raise ModbusIOError(f"{method_name} -> ошибка устройства: {result}")
        return result

    # ------------------------------------------------------------------ #
    # Чтение
    # ------------------------------------------------------------------ #

    def read_holding(self, address: int, count: int) -> list[int]:
        """Читать holding-регистры (FC=03)."""
        return list(self._call("read_holding_registers", address, count=count).registers)

    def read_input(self, address: int, count: int) -> list[int]:
        """Читать input-регистры (FC=04)."""
        return list(self._call("read_input_registers", address, count=count).registers)

    def read_coils(self, address: int, count: int) -> list[bool]:
        """Читать coils (FC=01)."""
        return list(self._call("read_coils", address, count=count).bits)[:count]

    def read_discrete_inputs(self, address: int, count: int) -> list[bool]:
        """Читать discrete inputs (FC=02)."""
        return list(self._call("read_discrete_inputs", address, count=count).bits)[:count]

    # ------------------------------------------------------------------ #
    # Запись
    # ------------------------------------------------------------------ #

    def write_register(self, address: int, value: int) -> None:
        """Записать один holding-регистр (FC=06)."""
        self._call("write_register", address, value)

    def write_registers(self, address: int, values: list[int]) -> None:
        """Записать несколько holding-регистров (FC=16)."""
        self._call("write_registers", address, list(values))

    def write_coil(self, address: int, value: bool) -> None:
        """Записать один coil (FC=05)."""
        self._call("write_coil", address, bool(value))
