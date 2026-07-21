"""GenericModbusDriver — универсальный драйвер для простых register-устройств.

Самый простой драйвер — образец «новое устройство без кода»:
    tick() — прочитать все access=r/rw записи карты -> snapshot {values: {...}}
    call: read {name}, write {values} — с валидацией access/min/max из meta.

Транспорт строится через build_transport (tcp/rtu/bridge).
"""

from __future__ import annotations

from typing import Any

from Services.device_hub.drivers.base import BaseDeviceDriver


class GenericModbusDriver(BaseDeviceDriver):
    """Универсальный Modbus-драйвер: poll протокола + read/write.

    Args:
        entry:     DeviceEntry с kind=generic_modbus.
        protocol:  DeviceProtocol (обязателен — без него нечего читать).
        transport: Инъекция RegisterTransport для тестов.
    """

    kind = "generic_modbus"

    def __init__(
        self,
        entry: Any,
        protocol: Any = None,
        *,
        transport: Any = None,
        clock: Any = None,
        sleep: Any = None,
    ) -> None:
        super().__init__(entry, protocol, clock=clock, sleep=sleep)
        self._transport = transport
        self._device: Any = None  # RegisterTransport (ModbusDevice или bridge)

    # ------------------------------------------------------------------ #
    # Соединение
    # ------------------------------------------------------------------ #

    @property
    def is_connected(self) -> bool:
        if self._device is not None:
            return self._device.is_connected
        return False

    @property
    def transport(self) -> Any:
        """RegisterTransport устройства."""
        return self._device

    def connect(self) -> bool:
        """Построить транспорт и подключиться."""
        if self._transport is not None:
            self._device = self._transport
        elif self._device is None:
            from Services.device_hub.transports import build_transport

            try:
                self._device = build_transport(self.entry, lambda _: None)
            except Exception:
                self._record_err()
                self._last_quality = "bad"
                return False

        try:
            if hasattr(self._device, "connect"):
                ok = self._device.connect()
                self._last_quality = "good" if ok else "bad"
                return ok
            self._last_quality = "good"
            return True
        except Exception:
            self._record_err()
            self._last_quality = "bad"
            return False

    def disconnect(self) -> None:
        if self._device is not None and hasattr(self._device, "disconnect"):
            try:
                self._device.disconnect()
            except Exception:
                pass
        self._last_quality = "bad"

    # ------------------------------------------------------------------ #
    # Tick
    # ------------------------------------------------------------------ #

    def tick(self, stop_event: Any = None) -> dict | None:
        """Прочитать все r/rw-записи протокола -> snapshot."""
        if not self.is_connected or self.protocol is None:
            return self.snapshot(quality="bad")

        values: dict[str, Any] = {}
        total = 0
        for name, meta in self.protocol.meta.items():
            if meta.access in ("r", "rw"):
                total += 1
                try:
                    t0 = self._clock()
                    val = self.protocol.register_map.read(self._device, name)
                    latency = (self._clock() - t0) * 1000
                    self._record_ok(latency)
                    values[name] = val
                except Exception:
                    self._record_err()

        # A-13 (bug-hunt 2026-07-20): раньше quality="good" ставился при ЛЮБОМ
        # непустом values — частичное чтение (1 регистр из 10) маскировалось
        # под полный успех, потребитель принимал неполные данные как надёжные.
        # Теперь good — только полный набор; частичный — "stale" (тот же
        # деградированный код, что у vfd_driver при bridge_alive=False);
        # полный провал/нет r-записей вовсе — "bad".
        if total == 0 or not values:
            quality = "bad"
        elif len(values) == total:
            quality = "good"
        else:
            quality = "stale"

        return self.snapshot(data={"values": values}, quality=quality)

    # ------------------------------------------------------------------ #
    # Call
    # ------------------------------------------------------------------ #

    def call(self, op: str, args: dict) -> dict:
        """read {name} / write {values}."""
        if op == "read":
            return self._call_read(args)
        elif op == "write":
            return self._call_write(args)
        return {"status": "error", "message": f"Неизвестная операция generic_modbus: {op!r}"}

    def _call_read(self, args: dict) -> dict:
        name = args.get("name", "")
        if not name or self.protocol is None:
            return {"status": "error", "message": "нужно: {name: str}"}
        if name not in self.protocol.meta:
            return {"status": "error", "message": f"запись {name!r} не найдена в протоколе"}
        meta = self.protocol.meta[name]
        if meta.access == "w":
            return {"status": "error", "message": f"запись {name!r} доступна только на запись"}
        try:
            val = self.protocol.register_map.read(self._device, name)
            self._record_ok()
            return {"status": "ok", "name": name, "value": val}
        except Exception as exc:
            self._record_err()
            return {"status": "error", "message": str(exc)}

    def _call_write(self, args: dict) -> dict:
        """Записать значения с валидацией access/min/max."""
        values = args.get("values", {})
        if not values or self.protocol is None:
            return {"status": "error", "message": "нужно: {values: {name: value}}"}

        # Валидация access и min/max
        for name, value in values.items():
            if name not in self.protocol.meta:
                return {"status": "error", "message": f"запись {name!r} не найдена в протоколе"}
            meta = self.protocol.meta[name]
            if meta.access == "r":
                return {"status": "error", "message": f"запись {name!r} доступна только на чтение"}
            if meta.min is not None and float(value) < meta.min:
                return {
                    "status": "error",
                    "message": f"значение {name}={value} меньше минимума {meta.min}",
                }
            if meta.max is not None and float(value) > meta.max:
                return {
                    "status": "error",
                    "message": f"значение {name}={value} больше максимума {meta.max}",
                }

        try:
            ops = self.protocol.register_map.write_ops(values)
            self._device.transaction(ops)
            self._record_ok()
            return {"status": "ok", "written": list(values.keys())}
        except Exception as exc:
            self._record_err()
            return {"status": "error", "message": str(exc)}
