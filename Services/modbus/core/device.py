"""ModbusDevice — высокоуровневый драйвер одного устройства Modbus.

Объединяет:
- конфиг (ModbusConfig);
- sdk-клиент (ModbusSdkClient, транспорт TCP/RTU);
- state machine + телеметрию (ConnectionState / ModbusStatus);
- thread-safe доступ (один Lock на все операции) — клиент pymodbus не потокобезопасен;
- callbacks on_status / on_error / on_data — «полноценная система»: статусы, ошибки и
  данные уходят наружу через API, а не только значения регистров.

Слой core НЕ зависит от фреймворка — это чистый Python, пригодный для standalone-
использования (см. __main__.py) и для оборачивания плагином/каналом.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from Services.modbus.core.config import ModbusConfig
from Services.modbus.core.status import ConnectionState, ModbusStatus
from Services.modbus.sdk.client import ModbusSdkClient
from Services.modbus.sdk.errors import ModbusDriverError

StatusCallback = Callable[[dict[str, Any]], None]
ErrorCallback = Callable[[str], None]
DataCallback = Callable[[dict[str, Any]], None]


class ModbusDevice:
    """Потокобезопасный драйвер устройства Modbus (клиент/master).

    Пример::

        dev = ModbusDevice(ModbusConfig(host="192.168.1.10"))
        dev.connect()
        regs = dev.read_holding(0, 10)
        dev.write_register(0, 42)
        print(dev.get_status())
        dev.disconnect()
    """

    def __init__(
        self,
        config: ModbusConfig,
        *,
        client: ModbusSdkClient | None = None,
        on_status: StatusCallback | None = None,
        on_error: ErrorCallback | None = None,
        on_data: DataCallback | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cfg = config
        self._client = client if client is not None else ModbusSdkClient(config)
        self._on_status = on_status
        self._on_error = on_error
        self._on_data = on_data
        self._clock = clock
        self._lock = threading.RLock()
        self._status = ModbusStatus()

    # ------------------------------------------------------------------ #
    # Свойства
    # ------------------------------------------------------------------ #

    @property
    def config(self) -> ModbusConfig:
        """Текущий конфиг."""
        return self._cfg

    @property
    def state(self) -> ConnectionState:
        """Текущее состояние соединения."""
        return self._status.state

    @property
    def is_connected(self) -> bool:
        """True, если соединение установлено."""
        return self._status.is_connected

    def get_status(self) -> dict[str, Any]:
        """Снимок статуса/счётчиков в dict (API наружу)."""
        with self._lock:
            return self._status.to_dict(now=self._clock())

    # ------------------------------------------------------------------ #
    # Управление соединением
    # ------------------------------------------------------------------ #

    def connect(self) -> bool:
        """Подключиться к устройству. Возвращает True при успехе."""
        with self._lock:
            self._set_state(ConnectionState.CONNECTING)
            try:
                self._client.connect()
            except ModbusDriverError as exc:
                self._fail(str(exc))
                return False
            self._status.connected_since = self._clock()
            self._status.last_error = ""
            self._set_state(ConnectionState.CONNECTED)
            return True

    def disconnect(self) -> None:
        """Штатно закрыть соединение."""
        with self._lock:
            self._client.close()
            self._status.connected_since = None
            self._set_state(ConnectionState.DISCONNECTED)

    # ------------------------------------------------------------------ #
    # Операции чтения (с телеметрией)
    # ------------------------------------------------------------------ #

    def read_holding(self, address: int, count: int = 1) -> list[int]:
        """Читать holding-регистры (FC=03)."""
        return self._read("read_holding", address, count, kind="holding")

    def read_input(self, address: int, count: int = 1) -> list[int]:
        """Читать input-регистры (FC=04)."""
        return self._read("read_input", address, count, kind="input")

    def read_coils(self, address: int, count: int = 1) -> list[bool]:
        """Читать coils (FC=01)."""
        return self._read("read_coils", address, count, kind="coils")

    def read_discrete_inputs(self, address: int, count: int = 1) -> list[bool]:
        """Читать discrete inputs (FC=02)."""
        return self._read("read_discrete_inputs", address, count, kind="discrete")

    # ------------------------------------------------------------------ #
    # Операции записи (с телеметрией)
    # ------------------------------------------------------------------ #

    def write_register(self, address: int, value: int) -> bool:
        """Записать один holding-регистр (FC=06)."""
        return self._write("write_register", address, value)

    def write_registers(self, address: int, values: list[int]) -> bool:
        """Записать несколько holding-регистров (FC=16)."""
        return self._write("write_registers", address, values)

    def write_coil(self, address: int, value: bool) -> bool:
        """Записать один coil (FC=05)."""
        return self._write("write_coil", address, value)

    # ------------------------------------------------------------------ #
    # Внутреннее
    # ------------------------------------------------------------------ #

    def _read(self, method: str, address: int, count: int, *, kind: str) -> Any:
        with self._lock:
            try:
                result = getattr(self._client, method)(address, count)
            except ModbusDriverError as exc:
                self._status.reads_err += 1
                self._fail(str(exc))
                raise
            self._status.reads_ok += 1
            self._status.last_op_ts = self._clock()
            self._emit_data({"op": method, "kind": kind, "address": address, "values": result})
            return result

    def _write(self, method: str, address: int, value: Any) -> bool:
        with self._lock:
            try:
                getattr(self._client, method)(address, value)
            except ModbusDriverError as exc:
                self._status.writes_err += 1
                self._fail(str(exc))
                raise
            self._status.writes_ok += 1
            self._status.last_op_ts = self._clock()
            self._emit_data({"op": method, "address": address, "value": value})
            return True

    def _set_state(self, state: ConnectionState) -> None:
        """Сменить состояние и уведомить подписчиков (on_status)."""
        self._status.state = state
        self._emit_status()

    def _fail(self, message: str) -> None:
        """Зафиксировать ошибку: state=ERROR, last_error, callbacks."""
        self._status.last_error = message
        self._status.state = ConnectionState.ERROR
        if self._on_error is not None:
            self._on_error(message)
        self._emit_status()

    def _emit_status(self) -> None:
        if self._on_status is not None:
            self._on_status(self._status.to_dict(now=self._clock()))

    def _emit_data(self, payload: dict[str, Any]) -> None:
        if self._on_data is not None:
            self._on_data(payload)
