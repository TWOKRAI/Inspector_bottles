"""FakeRobotTransport — in-process транспорт для тестов без сети и pymodbus.

Реализует ``DeviceTransport`` (structural) поверх ``RobotSimCore``: каждое
чтение продвигает «Motion-цикл» фейк-робота на ``ticks_per_read`` тиков, так
что поллинг клиента (is_free / job_accepted / draw_busy) детерминированно
двигает время — без sleep'ов и реальных таймеров.

Основной тестовый стенд robot_comm/vfd_comm (~90% тестов); TCP sim_robot —
только E2E и ручная разработка GUI.
"""

from __future__ import annotations

from typing import Any

from Services.modbus.sdk.errors import ModbusConnectionError, ModbusIOError

from Services.robot_comm.server.sim_core import RobotSimCore


class FakeRobotTransport:
    """DeviceTransport поверх RobotSimCore.

    Args:
        core:           Внешний RobotSimCore (или создаётся свой).
        ticks_per_read: Сколько тиков Motion-цикла приходится на одно чтение.
    """

    def __init__(self, core: RobotSimCore | None = None, *, ticks_per_read: int = 1) -> None:
        self.core = core if core is not None else RobotSimCore()
        self.ticks_per_read = ticks_per_read
        self._connected = False
        self.fail_next_op = False  # инъекция сбоя: следующая операция упадёт
        self.transactions: list[list[tuple]] = []

    # --- DeviceTransport: lifecycle ---

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def get_status(self) -> dict[str, Any]:
        return {"state": "connected" if self._connected else "disconnected", "fake": True}

    # --- DeviceTransport: RegisterTransport ---

    def read_registers(self, address: int, count: int = 1) -> list[int]:
        self._check("read_registers")
        for _ in range(self.ticks_per_read):
            self.core.tick()
        return self.core.read(address, count)

    def transaction(self, ops: list[tuple]) -> bool:
        self._check("transaction")
        self.transactions.append(list(ops))
        for kind, address, value in ops:
            if kind == "w":
                self.core.write(address, [int(value)])
            elif kind == "wm":
                self.core.write(address, list(value))
            else:
                raise ValueError(f"transaction: неизвестная операция {kind!r}")
        return True

    # --- внутреннее ---

    def _check(self, op: str) -> None:
        if not self._connected:
            raise ModbusConnectionError(f"fake: {op} без соединения")
        if self.fail_next_op:
            self.fail_next_op = False
            raise ModbusIOError(f"fake: {op} failed (инъекция)")
