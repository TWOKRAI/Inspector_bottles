"""ModbusSinkPlugin — вывод метаданных кадра по Modbus (тест/симуляция).

Лист-узел в конце цепочки (параллельно дисплею): после обработки каждого кадра
пишет ``[width, height, frame_id]`` в holding-регистры ``base_address..+2`` через
``Services.modbus.ModbusDevice``. Pass-through: кадр идёт дальше без изменений
(у листа chain_targets пуст, так что фактически узел терминальный).

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

from .registers import ModbusSinkRegisters

# Регистр Modbus — 16-бит беззнаковый: значения сворачиваем по модулю.
_U16 = 65536
# Минимальный интервал между попытками переподключения, сек.
_RECONNECT_THROTTLE_SEC = 2.0


@register_plugin(
    "modbus_sink",
    category="sink",
    description="Вывод метаданных кадра (width/height/frame_id) по Modbus-TCP / RS485",
)
class ModbusSinkPlugin(ProcessModulePlugin):
    """Sink-плагин: пишет размер и id кадра в holding-регистры PLC/симулятора."""

    name = "modbus_sink"
    category = "sink"
    # НЕ thread_safe: держит единственное Modbus-соединение (не параллелить воркерами).
    thread_safe = False

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Входной кадр"),
    ]
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Pass-through кадра"),
    ]

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
    def _frame_size(item: dict) -> tuple[int, int]:
        """Размер кадра: из метаданных item, иначе из frame.shape. Кламп в u16."""
        w = item.get("width")
        h = item.get("height")
        if not (isinstance(w, int) and isinstance(h, int)):
            frame = item.get("frame")
            if frame is not None and getattr(frame, "shape", None) is not None:
                h, w = int(frame.shape[0]), int(frame.shape[1])
            else:
                w, h = 0, 0
        return int(w) % _U16, int(h) % _U16

    def _write_item(self, item: dict) -> None:
        """Записать [width, height, frame_id] в holding-регистры (best-effort)."""
        if not self._ensure_connected():
            return
        width, height = self._frame_size(item)
        fid = int(item.get("frame_id", item.get("seq_id", 0))) % _U16
        values = [width, height, fid]
        try:
            self._device.write_registers(self._reg.base_address, values)
        except (ModbusDriverError, ValueError, TypeError) as exc:
            self._reg.last_error = str(exc)
            self._ctx.log_error(f"ModbusSinkPlugin: write failed: {exc}")
            return
        self._reg.writes_ok += 1
        self._reg.last_written = str(values)

    # ------------------------------------------------------------------ #
    # Callbacks телеметрии
    # ------------------------------------------------------------------ #

    def _on_status(self, status: dict) -> None:
        self._reg.conn_state = status.get("state", "unknown")

    def _on_error(self, message: str) -> None:
        self._reg.last_error = message
