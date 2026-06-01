"""ModbusChannel — драйвер Modbus как канал RouterManager.

P4: единый транспорт. Modbus работает «как канал» (IMessageChannel), наравне с
QueueChannel/SocketChannel, а не только через SHM/команды:

- OUTBOUND (система → PLC): router зовёт ``send(message)`` — команда read/write/connect
  превращается в операцию Modbus, возвращается статус-dict.
- INBOUND (PLC → система): ``poll(timeout)`` опрашивает заданные блоки регистров и
  отдаёт значения как router-сообщения; туда же попадают события смены статуса и
  ошибки (status/error через API — «полноценная система»).

Канал оборачивает ГОТОВЫЙ ModbusDevice (не создаёт второе соединение) и не зависит
от деталей pymodbus. Образец — SocketChannel (router_module/channels/socket_channel.py).
"""

from __future__ import annotations

from collections import deque
from typing import Any, Callable

from multiprocess_framework.modules.router_module.channels.base_channel import MessageChannel

from Services.modbus.core.device import ModbusDevice
from Services.modbus.core.poller import ModbusPoller, RegisterBlock
from Services.modbus.sdk.errors import ModbusDriverError

_READERS = {
    "holding": "read_holding",
    "input": "read_input",
    "coils": "read_coils",
    "discrete": "read_discrete_inputs",
}


class ModbusChannel(MessageChannel):
    """Канал Modbus поверх ModbusDevice (IMessageChannel).

    Args:
        name:        Имя канала (ключ маршрутизации, напр. "modbus_1").
        device:      Готовый ModbusDevice (соединением управляет канал/вызывающий).
        poll_blocks: Блоки для опроса в poll() (RegisterBlock или list[dict]-спеки).
        auto_connect: Подключаться при start().
        log_warning/log_error: инъекция логирования (или от RouterManager).
    """

    def __init__(
        self,
        name: str,
        device: ModbusDevice,
        *,
        poll_blocks: list[RegisterBlock] | list[dict] | None = None,
        auto_connect: bool = True,
        log_warning: Callable[[str], None] | None = None,
        log_error: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(log_warning=log_warning, log_error=log_error)
        self._name = name
        self._device = device
        self._auto_connect = auto_connect
        self._poller = self._make_poller(device, poll_blocks)

        # Очередь событий (смена статуса/ошибки) для выдачи через poll().
        self._events: deque[dict[str, Any]] = deque(maxlen=256)
        self._last_state: str | None = None
        self._last_error: str = ""

        self._rx = 0  # принято команд (send)
        self._tx = 0  # выдано сообщений (poll)

    @staticmethod
    def _make_poller(device: ModbusDevice, blocks: Any) -> ModbusPoller:
        if not blocks:
            return ModbusPoller(device, [])
        if isinstance(blocks[0], RegisterBlock):
            return ModbusPoller(device, list(blocks))
        return ModbusPoller.from_specs(device, list(blocks))

    # ---- IMessageChannel: свойства ----

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return "modbus"

    # ---- Жизненный цикл ----

    def start(self) -> bool:
        """Подключиться к устройству (если auto_connect)."""
        if self._auto_connect:
            return self._device.connect()
        return True

    def close(self) -> None:
        """Отключиться от устройства."""
        self._device.disconnect()

    # ---- OUTBOUND: система → PLC ----

    def send(self, message: dict[str, Any]) -> dict[str, Any]:
        """Выполнить команду Modbus из router-сообщения. Вернуть статус-dict.

        Поддерживаемые command (или поле "op"):
            modbus.read    {address, count, kind}      → {"status":"success","values":[...]}
            modbus.write   {address, value}            → {"status":"success"}
            modbus.write_many {address, values}        → {"status":"success"}
            modbus.connect / modbus.disconnect / modbus.status
        """
        self._rx += 1
        command = str(message.get("command") or message.get("op") or "").replace("modbus.", "")
        data = message.get("data", message)
        try:
            return self._dispatch(command, data)
        except ModbusDriverError as exc:
            self._log_error(f"[ModbusChannel:{self._name}] {command} failed: {exc}")
            return {"status": "error", "channel": self._name, "reason": str(exc)}

    def _dispatch(self, command: str, data: dict[str, Any]) -> dict[str, Any]:
        if command in ("read", "read_registers"):
            kind = str(data.get("kind", "holding"))
            reader = getattr(self._device, _READERS.get(kind, "read_holding"))
            values = reader(int(data.get("address", 0)), int(data.get("count", 1)))
            return {"status": "success", "channel": self._name, "values": values}
        if command in ("write", "write_register"):
            self._device.write_register(int(data["address"]), int(data["value"]))
            return {"status": "success", "channel": self._name}
        if command in ("write_many", "write_registers"):
            self._device.write_registers(int(data["address"]), list(data["values"]))
            return {"status": "success", "channel": self._name}
        if command == "connect":
            ok = self._device.connect()
            return {"status": "success" if ok else "error", "channel": self._name}
        if command == "disconnect":
            self._device.disconnect()
            return {"status": "success", "channel": self._name}
        if command in ("status", ""):
            return {"status": "success", "channel": self._name, **self._device.get_status()}
        return {"status": "error", "channel": self._name, "reason": f"unknown command: {command}"}

    # ---- INBOUND: PLC → система ----

    def poll(self, timeout: float = 0.0) -> list[dict[str, Any]]:
        """Опросить устройство: события статуса/ошибок + значения регистров.

        Возвращает router-сообщения (dict). Не блокирует (timeout игнорируется —
        Modbus pull синхронный и быстрый).
        """
        messages: list[dict[str, Any]] = []
        self._collect_status_event(messages)
        if self._device.is_connected and self._poller.blocks:
            values = self._poller.poll_once()
            messages.append(
                {
                    "channel": self._name,
                    "type": "data",
                    "command": "modbus.values",
                    "data": values,
                }
            )
        # Дренируем накопленные события (если появились во время операций).
        while self._events:
            messages.append(self._events.popleft())
        self._tx += len(messages)
        return messages

    def _collect_status_event(self, messages: list[dict[str, Any]]) -> None:
        """Сформировать событие при смене состояния/ошибки (status/error через канал)."""
        st = self._device.get_status()
        state, last_error = st["state"], st["last_error"]
        if state != self._last_state or last_error != self._last_error:
            messages.append(
                {
                    "channel": self._name,
                    "type": "event",
                    "command": "modbus.status",
                    "data": st,
                }
            )
            self._last_state = state
            self._last_error = last_error

    # ---- Мониторинг ----

    def get_info(self) -> dict[str, Any]:
        return {
            "name": self._name,
            "type": self.channel_type,
            "active": self._device.is_connected,
            "rx": self._rx,
            "tx": self._tx,
            "device": self._device.get_status(),
        }
