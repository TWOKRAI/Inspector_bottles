"""Состояние соединения и телеметрия Modbus-драйвера.

Полноценная система статусов: не только значения регистров, но и состояние
соединения, последняя ошибка и счётчики операций передаются наружу через API
(``ModbusStatus.to_dict``) и через callbacks (on_status/on_error) в плагине.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ConnectionState(str, Enum):
    """Состояние соединения Modbus-устройства.

    Допустимые переходы::

        DISCONNECTED -> CONNECTING -> CONNECTED
        CONNECTING   -> ERROR        (ошибка установки соединения)
        CONNECTED    -> ERROR        (ошибка операции/обрыв)
        CONNECTED    -> DISCONNECTED (штатное закрытие)
        ERROR        -> CONNECTING   (повторная попытка)
    """

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass(slots=True)
class ModbusStatus:
    """Снимок состояния и счётчиков драйвера.

    Передаётся наружу через ``to_dict`` (Dict at Boundary). Время хранится в
    монотонных секундах источника (заполняется устройством), поэтому сам класс
    не дёргает часы — это упрощает тестирование.

    Attributes:
        state:           Текущее состояние соединения.
        last_error:      Текст последней ошибки ("" если ошибок не было).
        connected_since: Монотонная метка момента подключения (None если не подключён).
        reads_ok:        Успешных операций чтения.
        reads_err:       Ошибочных операций чтения.
        writes_ok:       Успешных операций записи.
        writes_err:      Ошибочных операций записи.
        last_op_ts:      Метка последней операции (любой).
    """

    state: ConnectionState = ConnectionState.DISCONNECTED
    last_error: str = ""
    connected_since: float | None = None
    reads_ok: int = 0
    reads_err: int = 0
    writes_ok: int = 0
    writes_err: int = 0
    last_op_ts: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_connected(self) -> bool:
        """True, если соединение установлено."""
        return self.state is ConnectionState.CONNECTED

    @property
    def total_errors(self) -> int:
        """Суммарное число ошибок чтения и записи."""
        return self.reads_err + self.writes_err

    def uptime(self, now: float) -> float:
        """Длительность текущего соединения в секундах (0.0 если не подключён)."""
        if self.connected_since is None:
            return 0.0
        return max(0.0, now - self.connected_since)

    def to_dict(self, now: float | None = None) -> dict[str, Any]:
        """Сериализовать снимок в dict для API/IPC/телеметрии."""
        data: dict[str, Any] = {
            "state": self.state.value,
            "is_connected": self.is_connected,
            "last_error": self.last_error,
            "reads_ok": self.reads_ok,
            "reads_err": self.reads_err,
            "writes_ok": self.writes_ok,
            "writes_err": self.writes_err,
            "total_errors": self.total_errors,
            "last_op_ts": self.last_op_ts,
            "connected_since": self.connected_since,
        }
        if now is not None:
            data["uptime_sec"] = self.uptime(now)
        if self.extra:
            data["extra"] = dict(self.extra)
        return data
