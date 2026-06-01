"""ModbusSinkPlugin — универсальный вывод данных кадра по Modbus (тест/симуляция).

Лист-узел в конце цепочки (параллельно дисплею): после обработки каждого кадра пишет
УНИВЕРСАЛЬНЫЙ пакет в holding-регистры от ``base_address`` через
``Services.modbus.ModbusDevice``. Что писать — задаёт ``payload`` (см. registers):
любые поля item в любом количестве, со свёрткой списков (count/sum/max/min) и типом
u16/u32. Pass-through: кадр идёт дальше без изменений.

Заготовка под вывод результатов инспекции в PLC. Соединение открывается в
``start()``, закрывается в ``shutdown()``; ``process()`` только пишет. Если приёмник
ещё не поднят — throttled-reconnect, чтобы переживать запуск сервера после прото.

Импорты: фасад плагинов фреймворка + ``Services.modbus`` напрямую (ADR-DS-006 —
плагину запрещён только ``multiprocess_prototype.*``). Соединение живёт внутри
процесса-воркера, через IPC уходит только dict (Dict at Boundary).
"""

from __future__ import annotations

import time

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    register_plugin,
)

from Services.modbus import ModbusConfig, ModbusDevice, ModbusDriverError, TransportType
from Services.modbus.sdk.datatypes import encode_uint16, encode_uint32

from .registers import ModbusSinkRegisters

# Минимальный интервал между попытками переподключения, сек.
_RECONNECT_THROTTLE_SEC = 2.0


@register_plugin(
    "modbus_sink",
    category="sink",
    description="Универсальный вывод данных кадра (payload) по Modbus-TCP / RS485",
)
class ModbusSinkPlugin(ProcessModulePlugin):
    """Sink-плагин: пишет универсальный payload в holding-регистры PLC/симулятора."""

    name = "modbus_sink"
    category = "sink"
    # НЕ thread_safe: держит единственное Modbus-соединение (не параллелить воркерами).
    thread_safe = False

    # Универсальный вход: список детекций (или иные данные item). Лист — без выходов.
    inputs = [
        Port(name="data", dtype="list[dict]", shape="N", description="Данные для пакета (напр. detections)"),
    ]
    outputs = []

    commands = {}
    register_class = ModbusSinkRegisters

    @classmethod
    def config_class(cls) -> type | None:
        """Явный config_class → register_schema() резолвит register_bindings."""
        from .config import ModbusSinkPluginConfig

        return ModbusSinkPluginConfig

    # ------------------------------------------------------------------ #
    # LIFECYCLE
    # ------------------------------------------------------------------ #

    def configure(self, ctx: PluginContext) -> None:
        """IDLE → READY: инициализация register. Соединение НЕ открываем здесь."""
        self._ctx = ctx
        self._reg: ModbusSinkRegisters = self._init_register(ctx)
        self._device: ModbusDevice | None = None
        self._frame_counter = 0
        self._last_reconnect = 0.0
        ctx.log_info(
            f"ModbusSinkPlugin: configured ({self._reg.transport} "
            f"{self._reg.host}:{self._reg.port}, base={self._reg.base_address})"
        )

    def start(self, ctx: PluginContext) -> None:
        """READY → RUNNING: создать устройство и (опц.) подключиться."""
        self._device = self._build_device()
        if self._reg.auto_connect:
            self._try_connect()
        ctx.log_info("ModbusSinkPlugin: started")

    def shutdown(self, ctx: PluginContext) -> None:
        """* → STOPPED: закрыть соединение."""
        if self._device is not None:
            self._device.disconnect()
            self._device = None
        ctx.log_info("ModbusSinkPlugin: shutdown")

    # ------------------------------------------------------------------ #
    # PROCESS — запись после каждого кадра (pass-through)
    # ------------------------------------------------------------------ #

    def process(self, items: list[dict]) -> list[dict]:
        """Записать метаданные каждого N-го кадра в PLC; кадр пробросить дальше."""
        every_n = max(1, int(self._reg.write_every_n))
        for item in items:
            self._reg.frames_seen += 1
            self._frame_counter += 1
            if self._frame_counter % every_n == 0:
                self._write_item(item)
        return items

    # ------------------------------------------------------------------ #
    # Внутреннее
    # ------------------------------------------------------------------ #

    def _build_device(self) -> ModbusDevice:
        """Собрать ModbusDevice из текущих значений register."""
        r = self._reg
        config = ModbusConfig(
            transport=TransportType(str(r.transport).lower()),
            host=r.host,
            port=r.port,
            serial_port=r.serial_port,
            baudrate=r.baudrate,
            unit_id=r.unit_id,
            timeout_sec=r.timeout_sec,
        )
        return ModbusDevice(config, on_status=self._on_status, on_error=self._on_error)

    def _try_connect(self) -> bool:
        """Попытка подключения (best-effort). Возвращает is_connected."""
        if self._device is None:
            return False
        self._device.connect()  # ModbusDevice.connect ловит ошибки и возвращает bool
        return self._device.is_connected

    def _ensure_connected(self) -> bool:
        """Гарантировать соединение: throttled-reconnect если приёмник был недоступен."""
        if self._device is None:
            return False
        if self._device.is_connected:
            return True
        now = time.monotonic()
        if now - self._last_reconnect < _RECONNECT_THROTTLE_SEC:
            return False
        self._last_reconnect = now
        return self._try_connect()

    @staticmethod
    def _reduce(values: list, reduce: str) -> int:
        """Свернуть список числовых значений: sum | max | min (count считается выше)."""
        nums = [int(v) for v in values if isinstance(v, (int, float))]
        if not nums:
            return 0
        if reduce == "sum":
            return sum(nums)
        if reduce == "max":
            return max(nums)
        if reduce == "min":
            return min(nums)
        return 0

    def _resolve_value(self, item: dict, entry: dict) -> int:
        """Вычислить одно числовое значение payload-записи из item."""
        raw = item.get(entry.get("source"))
        reduce = entry.get("reduce")
        if not reduce:
            # Скаляр: берём как есть (None/нечисло → 0)
            try:
                return int(raw)
            except (TypeError, ValueError):
                return 0
        lst = raw if isinstance(raw, list) else []
        if reduce == "count":
            return len(lst)
        # sum/max/min по полю элементов (по умолчанию "area")
        field = entry.get("field", "area")
        field_values = [d.get(field, 0) for d in lst if isinstance(d, dict)]
        return self._reduce(field_values, reduce)

    def _build_registers(self, item: dict) -> list[int]:
        """Собрать список регистров из payload (u16=1 рег., u32=2 рег.)."""
        word_order = "little" if str(self._reg.word_order).lower() == "little" else "big"
        regs: list[int] = []
        for entry in self._reg.payload:
            if not isinstance(entry, dict):
                continue
            value = self._resolve_value(item, entry)
            if str(entry.get("dtype", "u16")).lower() == "u32":
                regs.extend(encode_uint32(int(value) & 0xFFFFFFFF, word_order))
            else:
                regs.extend(encode_uint16(int(value)))
        return regs

    def _write_item(self, item: dict) -> None:
        """Собрать payload и записать в holding-регистры (best-effort)."""
        if not self._ensure_connected():
            return
        regs = self._build_registers(item)
        if not regs:
            return
        try:
            self._device.write_registers(self._reg.base_address, regs)
        except (ModbusDriverError, ValueError, TypeError) as exc:
            self._reg.last_error = str(exc)
            self._ctx.log_error(f"ModbusSinkPlugin: write failed: {exc}")
            return
        self._reg.writes_ok += 1
        self._reg.last_written = str(regs)

    # ------------------------------------------------------------------ #
    # Callbacks телеметрии
    # ------------------------------------------------------------------ #

    def _on_status(self, status: dict) -> None:
        self._reg.conn_state = status.get("state", "unknown")

    def _on_error(self, message: str) -> None:
        self._reg.last_error = message
