"""Публичные контракты драйвера Modbus.

Protocol вместо ABC — structural subtyping, единственная точка зависимости для
внешних модулей. Любой класс с этими методами удовлетворяет протоколу без
явного наследования.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from Services.modbus.core.status import ConnectionState


@runtime_checkable
class RegisterTransport(Protocol):
    """Минимальный контракт «устройство как пространство регистров».

    Единственная точка зависимости для сервисов устройств (robot_comm,
    vfd_comm, ...): сервис описывает СВОЮ карту регистров и работает с любым
    транспортом, который умеет читать блоки и атомарно писать серии.

    Реализации:
    - ``ModbusDevice`` — прямое соединение (Modbus-TCP или RS485/RTU);
    - мост через другое устройство (например, RobotClient: ПК → робот по TCP,
      робот → ПЧ по RS-485 — для клиента ПЧ это просто регистры).

    Контракт ``transaction``: серия записей выполняется под одним замком,
    abort на первой ошибке (маркер-флаг — последняя операция серии).
    """

    @property
    def is_connected(self) -> bool:
        """Установлено ли соединение с устройством."""
        ...

    def read_registers(self, address: int, count: int = 1) -> list[int]:
        """Читать блок holding-регистров."""
        ...

    def transaction(self, ops: list[tuple]) -> bool:
        """Атомарная серия записей: ("w", addr, value) | ("wm", addr, [vals])."""
        ...


@runtime_checkable
class ModbusClientProtocol(Protocol):
    """Контракт высокоуровневого драйвера устройства Modbus."""

    @property
    def state(self) -> ConnectionState:
        """Текущее состояние соединения."""
        ...

    @property
    def is_connected(self) -> bool:
        """Установлено ли соединение."""
        ...

    def connect(self) -> bool:
        """Подключиться к устройству."""
        ...

    def disconnect(self) -> None:
        """Закрыть соединение."""
        ...

    def get_status(self) -> dict[str, Any]:
        """Снимок статуса/счётчиков (state, ошибки, телеметрия)."""
        ...

    def read_holding(self, address: int, count: int = 1) -> list[int]:
        """Читать holding-регистры."""
        ...

    def read_input(self, address: int, count: int = 1) -> list[int]:
        """Читать input-регистры."""
        ...

    def write_register(self, address: int, value: int) -> bool:
        """Записать один holding-регистр."""
        ...

    def write_registers(self, address: int, values: list[int]) -> bool:
        """Записать несколько holding-регистров."""
        ...
