"""Публичные контракты robot_comm (Protocol, structural subtyping)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from Services.robot_comm.core.datatypes import JobEcho, RobotPosition, Telemetry


@runtime_checkable
class DeviceTransport(Protocol):
    """Транспорт с жизненным циклом: RegisterTransport + connect/disconnect.

    Реализации: ``ModbusDevice`` (боевой TCP) и ``FakeRobotTransport`` (тесты).
    """

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
        """Снимок статуса/счётчиков транспорта."""
        ...

    def read_registers(self, address: int, count: int = 1) -> list[int]:
        """Читать блок holding-регистров."""
        ...

    def transaction(self, ops: list[tuple]) -> bool:
        """Атомарная серия записей (маркер — последним)."""
        ...


@runtime_checkable
class RobotClientProtocol(Protocol):
    """Контракт клиента робота — то, что видят плагины и UI.

    Клиент сам является RegisterTransport (read_registers/transaction) — это
    мост для vfd_comm: ПК -> робот по TCP, робот -> ПЧ по RS-485.
    """

    @property
    def is_connected(self) -> bool:
        """Установлено ли соединение с роботом."""
        ...

    def connect(self) -> bool:
        """Подключиться к роботу."""
        ...

    def disconnect(self) -> None:
        """Закрыть соединение."""
        ...

    def get_status(self) -> dict[str, Any]:
        """Статус транспорта (state, счётчики, ошибки)."""
        ...

    # --- режим ---
    def set_mode(self, mode: str) -> bool:
        """Переключить режим: ``cvt`` | ``draw`` (только когда робот свободен)."""
        ...

    # --- CVT ---
    def read_position(self) -> RobotPosition:
        """Текущая поза инструмента (для калибровки)."""
        ...

    def read_telemetry(self) -> Telemetry:
        """Полная телеметрия (блок 0x1130)."""
        ...

    def read_encoder(self) -> int:
        """Живой энкодер конвейера (DW)."""
        ...

    def is_free(self) -> bool:
        """Свободен ли робот для следующего задания."""
        ...

    def job_accepted(self) -> bool:
        """Принял ли робот последнее задание (флаг сброшен)."""
        ...

    def send_job(self, x_mm: float, y_mm: float, e_capture: int) -> bool:
        """Отправить CVT-задание (атомарно: X, Y, E_capture, маркер)."""
        ...

    def read_echo(self) -> JobEcho:
        """Эхо последнего принятого задания."""
        ...

    def stop(self, mode: int) -> bool:
        """Стоп: 1=домой+цикл, 2=домой+выход, 3=на месте."""
        ...

    def set_servo(self, on: bool) -> bool:
        """Серво ON/OFF."""
        ...

    # --- конфиг ---
    def get_config(self) -> dict[str, Any]:
        """Прочитать конфиг-блок робота."""
        ...

    def set_config(self, **fields: float) -> bool:
        """Записать поля конфиг-блока (read-modify-write + маркер)."""
        ...

    # --- мост (RegisterTransport) ---
    def read_registers(self, address: int, count: int = 1) -> list[int]:
        """Читать регистры робота (мост для vfd_comm)."""
        ...

    def transaction(self, ops: list[tuple]) -> bool:
        """Атомарная серия записей (мост для vfd_comm)."""
        ...
