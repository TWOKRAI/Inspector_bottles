"""ModbusPlugin — io-плагин драйвера Modbus-TCP / RS485 для pipeline.

Объединяет core.ModbusDevice с инфраструктурой процесса:
- чтение (вход): фоновый poll-worker опрашивает регистры → телеметрия в register,
  значения в state_proxy (live-GUI);
- запись (выход): process(items) пишет поле результата (например verdict) в PLC;
- команды из GUI: connect/disconnect/read/write/get_status через RouterManager;
- статусы/ошибки/счётчики прокидываются наружу через register-телеметрию,
  callbacks on_status/on_error и команду get_status — «полноценная система».

Слой Services → framework. Плагин не импортирует prototype/Plugins.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from multiprocess_framework.modules.process_module.plugins import (
    ExecutionMode,
    PluginContext,
    Port,
    ProcessModulePlugin,
    ThreadConfig,
    register_plugin,
)

from Services.modbus.core.config import ModbusConfig
from Services.modbus.core.device import ModbusDevice
from Services.modbus.sdk.errors import ModbusDriverError

from .registers import ModbusRegisters

_POLL_WORKER = "modbus_poll_worker"

_READERS = {
    "holding": "read_holding",
    "input": "read_input",
    "coils": "read_coils",
    "discrete": "read_discrete_inputs",
}


@register_plugin("modbus", category="io", description="Modbus-TCP / RS485 драйвер (PLC, регистры)")
class ModbusPlugin(ProcessModulePlugin):
    """Драйвер Modbus как io-плагин (чтение + запись + команды)."""

    name = "modbus"
    category = "io"

    inputs = [Port(name="result", dtype="dict", shape="(*,)", description="Результат для записи в PLC")]
    outputs = [Port(name="result", dtype="dict", shape="(*,)", description="Pass-through результата")]

    commands = {
        "connect": "cmd_connect",
        "disconnect": "cmd_disconnect",
        "read_registers": "cmd_read_registers",
        "write_register": "cmd_write_register",
        "get_status": "cmd_get_status",
    }
    register_class = ModbusRegisters

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def configure(self, ctx: PluginContext) -> None:
        """Инициализация register; устройство создаётся в start()."""
        self._ctx = ctx
        self._reg: ModbusRegisters = self._init_register(ctx)
        self._device: ModbusDevice | None = None
        self._channel: Any = None
        self._lock = threading.Lock()
        ctx.log_info(f"ModbusPlugin: configured ({self._reg.transport} {self._reg.host}:{self._reg.port})")

    def start(self, ctx: PluginContext) -> None:
        """Создать устройство, (опц.) подключиться, запустить poll-worker, зарегистрировать канал."""
        self._device = ModbusDevice(
            self._build_config(),
            on_status=self._on_status,
            on_error=self._on_error,
        )
        if self._reg.auto_connect:
            self._device.connect()
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker(_POLL_WORKER, self._poll_loop, cfg, auto_start=True)
        self._register_channel(ctx)
        ctx.log_info("ModbusPlugin: started")

    def shutdown(self, ctx: PluginContext) -> None:
        """Снять канал и отключиться от устройства."""
        self._unregister_channel(ctx)
        if self._device is not None:
            self._device.disconnect()
            self._device = None
        ctx.log_info("ModbusPlugin: shutdown")

    # ------------------------------------------------------------------ #
    # P4 — интеграция в RouterManager как канал
    # ------------------------------------------------------------------ #

    def _register_channel(self, ctx: PluginContext) -> None:
        """Зарегистрировать ModbusChannel в RouterManager (если доступен).

        Драйвер становится каналом единого транспорта: команды read/write идут через
        send(), значения/статусы/ошибки — через poll(). Образец — SocketChannel.
        """
        router = getattr(ctx, "router_manager", None)
        if router is None or self._device is None:
            self._channel = None
            return
        from Services.modbus.channels.modbus_channel import ModbusChannel
        from Services.modbus.core.poller import RegisterBlock, RegisterKind

        block = RegisterBlock(
            name="poll",
            kind=RegisterKind(self._reg.poll_kind),
            address=self._reg.poll_address,
            count=self._reg.poll_count,
        )
        self._channel = ModbusChannel(
            name=f"modbus_{self._reg.unit_id}",
            device=self._device,
            poll_blocks=[block],
            auto_connect=False,  # соединением управляет плагин
            log_warning=ctx.log_info,
            log_error=ctx.log_error,
        )
        try:
            router.register_channel(self._channel)
            ctx.log_info(f"ModbusPlugin: канал '{self._channel.name}' зарегистрирован в RouterManager")
        except Exception as exc:  # noqa: BLE001 - регистрация канала не критична для работы плагина
            ctx.log_error(f"ModbusPlugin: register_channel failed: {exc}")
            self._channel = None

    def _unregister_channel(self, ctx: PluginContext) -> None:
        """Снять канал с регистрации в RouterManager."""
        channel = getattr(self, "_channel", None)
        router = getattr(ctx, "router_manager", None)
        if channel is None or router is None:
            return
        try:
            router.unregister_channel(channel.name)
        except Exception as exc:  # noqa: BLE001
            ctx.log_error(f"ModbusPlugin: unregister_channel failed: {exc}")
        self._channel = None

    # ------------------------------------------------------------------ #
    # Data flow — запись результата в PLC (выход)
    # ------------------------------------------------------------------ #

    def process(self, items: list[dict]) -> list[dict]:
        """Output-режим: записать поле результата в регистр PLC. Pass-through."""
        if not (self._reg.write_enabled and self._device and self._device.is_connected):
            return items
        for item in items:
            if self._reg.write_field not in item:
                continue
            try:
                value = int(item[self._reg.write_field])
                self._device.write_register(self._reg.write_address, value)
            except (ModbusDriverError, ValueError, TypeError) as exc:
                self._ctx.log_error(f"ModbusPlugin: write failed: {exc}")
        return items

    # ------------------------------------------------------------------ #
    # Poll worker — чтение регистров (вход)
    # ------------------------------------------------------------------ #

    def _poll_loop(self, stop_event: Any, pause_event: Any) -> None:
        """Периодический опрос регистров с интервалом poll_interval_ms."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            time.sleep(max(0.01, self._reg.poll_interval_ms / 1000.0))
            self._poll_once()

    def _poll_once(self) -> None:
        """Один проход опроса + синхронизация телеметрии."""
        if self._device is None or not self._device.is_connected:
            return
        reader_name = _READERS.get(self._reg.poll_kind, "read_holding")
        try:
            values = getattr(self._device, reader_name)(self._reg.poll_address, self._reg.poll_count)
        except ModbusDriverError:
            self._sync_telemetry()
            return
        self._reg.last_values = str(values)
        self._sync_telemetry()
        self._push_state(values)

    def _push_state(self, values: list[Any]) -> None:
        """Опубликовать значения в реактивное дерево состояния (live-GUI)."""
        proxy = getattr(self._ctx, "state_proxy", None)
        if proxy is None:
            return
        try:
            proxy.set(f"modbus/{self._reg.unit_id}/values", {"values": values})
        except Exception:  # noqa: BLE001 - публикация телеметрии не критична
            pass

    # ------------------------------------------------------------------ #
    # Телеметрия / callbacks — статусы и ошибки через API
    # ------------------------------------------------------------------ #

    def _sync_telemetry(self) -> None:
        """Скопировать статус устройства в readonly-поля register (для GUI)."""
        if self._device is None:
            return
        st = self._device.get_status()
        self._reg.conn_state = st["state"]
        self._reg.last_error = st["last_error"]
        self._reg.reads_ok = st["reads_ok"]
        self._reg.writes_ok = st["writes_ok"]
        self._reg.total_errors = st["total_errors"]

    def _on_status(self, status: dict[str, Any]) -> None:
        self._reg.conn_state = status["state"]
        self._ctx.log_info(f"ModbusPlugin: state={status['state']}")

    def _on_error(self, message: str) -> None:
        self._reg.last_error = message
        self._ctx.log_error(f"ModbusPlugin: {message}")

    # ------------------------------------------------------------------ #
    # Команды из GUI
    # ------------------------------------------------------------------ #

    def _build_config(self) -> ModbusConfig:
        """Собрать ModbusConfig из текущих значений register."""
        r = self._reg
        return ModbusConfig(
            transport=r.transport,  # type: ignore[arg-type]
            host=r.host,
            port=r.port,
            serial_port=r.serial_port,
            baudrate=r.baudrate,
            unit_id=r.unit_id,
            timeout_sec=r.timeout_sec,
        )

    def cmd_connect(self, data: dict) -> dict:
        """Подключиться (пересоздаёт устройство по актуальному конфигу)."""
        with self._lock:
            self._device = ModbusDevice(self._build_config(), on_status=self._on_status, on_error=self._on_error)
            ok = self._device.connect()
        self._sync_telemetry()
        return {"status": "ok" if ok else "error", "state": self._reg.conn_state}

    def cmd_disconnect(self, data: dict) -> dict:
        """Отключиться от устройства."""
        with self._lock:
            if self._device is not None:
                self._device.disconnect()
        self._sync_telemetry()
        return {"status": "ok", "state": self._reg.conn_state}

    def cmd_read_registers(self, data: dict) -> dict:
        """Прочитать произвольный блок регистров (для наладки из GUI)."""
        if self._device is None or not self._device.is_connected:
            return {"status": "error", "error": "not connected"}
        address = int(data.get("address", self._reg.poll_address))
        count = int(data.get("count", self._reg.poll_count))
        kind = str(data.get("kind", self._reg.poll_kind))
        reader = getattr(self._device, _READERS.get(kind, "read_holding"))
        try:
            values = reader(address, count)
        except ModbusDriverError as exc:
            return {"status": "error", "error": str(exc)}
        return {"status": "ok", "address": address, "values": values}

    def cmd_write_register(self, data: dict) -> dict:
        """Записать значение в регистр (для наладки из GUI)."""
        if self._device is None or not self._device.is_connected:
            return {"status": "error", "error": "not connected"}
        address = int(data.get("address", self._reg.write_address))
        value = int(data.get("value", 0))
        try:
            self._device.write_register(address, value)
        except ModbusDriverError as exc:
            return {"status": "error", "error": str(exc)}
        return {"status": "ok", "address": address, "value": value}

    def cmd_get_status(self, data: dict) -> dict:
        """Вернуть полную телеметрию устройства (статус, счётчики, ошибки)."""
        if self._device is None:
            return {"status": "ok", "state": "disconnected", "connected": False}
        st = self._device.get_status()
        return {"status": "ok", **st}
