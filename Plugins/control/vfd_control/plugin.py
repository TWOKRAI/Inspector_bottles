"""VfdControlPlugin — управление ПЧ (лентой конвейера) через мост робота.

ПОТРЕБИТЕЛЬ соединения: клиента робота НЕ создаёт — берёт опубликованный
владельцем (robot_io) из ``Services.robot_comm.runtime``. Оба плагина обязаны
жить в ОДНОМ ``process_name`` рецепта.

Опрос статуса — фоновый worker через ``VfdClient.poll()``: пульс VFD_FLAG
(зеркало в текущем Lua обновляется ТОЛЬКО по команде) + контроль живости
моста по динамике heartbeat. Статус публикуется в register-поля и в
state-дерево (``vfd/status``).

Ограничение безопасности текущего Lua: команды ПЧ обслуживаются только в
CVT-ветке между заданиями — в DRAW-режиме и во время job «Stop ПЧ» НЕ
сработает (GUI дизейблит кнопки до Lua-улучшения №2).
"""

from __future__ import annotations

import time
from typing import Any

from multiprocess_framework.modules.process_module.plugins import (
    ExecutionMode,
    PluginContext,
    ProcessModulePlugin,
    ThreadConfig,
    register_plugin,
)

from Services.modbus import ModbusDriverError
from Services.robot_comm import RobotNotConnectedError, runtime
from Services.vfd_comm import VfdBridgeStaleError, VfdClient, VfdConfig, VfdFrequencyError

from .registers import VfdControlRegisters


@register_plugin(
    "vfd_control",
    category="control",
    description="ПЧ INVT GD20 (лента конвейера) через RS-485-мост робота",
)
class VfdControlPlugin(ProcessModulePlugin):
    """Управление ПЧ: run/stop/set_freq/reset + poll-зеркало в state."""

    name = "vfd_control"
    category = "control"
    thread_safe = False

    inputs = []  # команды — round-trip; поток кадров не нужен
    outputs = []

    commands = {
        "vfd_run": "cmd_run",
        "vfd_set_freq": "cmd_set_freq",
        "vfd_stop": "cmd_stop",
        "vfd_reset_fault": "cmd_reset_fault",
        "get_vfd_status": "cmd_get_status",
    }
    register_class = VfdControlRegisters

    @classmethod
    def config_class(cls) -> type | None:
        """Явный config_class → register_schema() резолвит register_bindings."""
        from .config import VfdControlPluginConfig

        return VfdControlPluginConfig

    # ------------------------------------------------------------------ #
    # LIFECYCLE
    # ------------------------------------------------------------------ #

    def configure(self, ctx: PluginContext) -> None:
        """IDLE → READY: register + ленивый клиент (мост появится после старта владельца)."""
        self._ctx = ctx
        self._reg: VfdControlRegisters = self._init_register(ctx)
        self._vfd: VfdClient | None = None
        ctx.log_info("VfdControlPlugin: configured (мост через robot_io)")

    def start(self, ctx: PluginContext) -> None:
        """READY → RUNNING: поднять poll-worker (клиент возьмём лениво в нём)."""
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker("vfd_poll", self._poll_loop, cfg, auto_start=True)
        ctx.log_info("VfdControlPlugin: started")

    def shutdown(self, ctx: PluginContext) -> None:
        """* → STOPPED: клиент НЕ закрываем — соединением владеет robot_io."""
        self._vfd = None
        ctx.log_info("VfdControlPlugin: shutdown")

    # ------------------------------------------------------------------ #
    # POLL-WORKER
    # ------------------------------------------------------------------ #

    def _poll_loop(self, stop_event, pause_event) -> None:
        """Фон: пульс-опрос зеркала ПЧ + живость моста + публикация статуса."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            time.sleep(self._reg.poll_interval_s)
            vfd = self._get_vfd()
            if vfd is None or not vfd.is_connected:
                continue
            try:
                status = vfd.poll()
            except ModbusDriverError as exc:
                self._set_error(f"poll: {exc}")
                continue
            self._apply_status(status)
            try:
                vfd.ensure_alive()
                self._reg.bridge_alive = True
            except VfdBridgeStaleError as exc:
                if self._reg.bridge_alive:  # лог только на переходе
                    self._set_error(str(exc))
                self._reg.bridge_alive = False

    def _get_vfd(self) -> VfdClient | None:
        """Лениво создать VfdClient поверх клиента робота из runtime (мост)."""
        if self._vfd is not None:
            return self._vfd
        try:
            transport = runtime.get_client()
        except RobotNotConnectedError:
            return None  # владелец ещё не стартовал — ждём следующего тика
        self._vfd = VfdClient(
            transport,
            VfdConfig(
                freq_min_hz=self._reg.freq_min_hz,
                freq_max_hz=self._reg.freq_max_hz,
                default_freq_hz=self._reg.default_freq_hz,
                stale_polls_limit=self._reg.stale_polls_limit,
            ),
        )
        self._ctx.log_info("VfdControlPlugin: мост получен (RobotClient из runtime)")
        return self._vfd

    def _apply_status(self, status) -> None:
        """Зеркало -> register-поля + state-дерево."""
        self._reg.running = status.running
        self._reg.out_freq_hz = status.out_freq_hz
        self._reg.current_a = status.current_a
        self._reg.dcbus_v = status.dcbus_v
        self._reg.fault = status.fault
        self._reg.heartbeat = status.heartbeat or 0
        self._reg.comm_errors = status.comm_errors or 0
        if self._ctx.state_proxy is not None:
            self._ctx.state_proxy.merge("vfd/status", {**status.to_dict(), "bridge_alive": self._reg.bridge_alive})

    def _set_error(self, message: str) -> None:
        self._reg.last_error = message
        self._ctx.log_error(f"VfdControlPlugin: {message}")

    # ------------------------------------------------------------------ #
    # КОМАНДЫ
    # ------------------------------------------------------------------ #

    def cmd_run(self, data: dict) -> dict:
        """Запустить: {freq?: Гц, reverse?: bool}."""
        freq = data.get("freq")
        reverse = bool(data.get("reverse", False))
        return self._safe_call(
            lambda vfd: vfd.run(float(freq) if freq is not None else None, reverse=reverse),
            extra={"freq": freq, "reverse": reverse},
        )

    def cmd_set_freq(self, data: dict) -> dict:
        """Сменить частоту на ходу: {hz: float}."""
        try:
            hz = float(data["hz"])
        except (KeyError, TypeError, ValueError):
            return {"status": "error", "message": "нужно: {hz: float}"}
        return self._safe_call(lambda vfd: vfd.set_freq(hz), extra={"hz": hz})

    def cmd_stop(self, _data: dict) -> dict:
        """Остановить вращение."""
        return self._safe_call(lambda vfd: vfd.stop())

    def cmd_reset_fault(self, _data: dict) -> dict:
        """Сбросить аварию."""
        return self._safe_call(lambda vfd: vfd.reset_fault())

    def cmd_get_status(self, _data: dict) -> dict:
        """Свежий статус по запросу (poll)."""
        return self._safe_call(lambda vfd: {"vfd": vfd.poll().to_dict(), "bridge_alive": self._reg.bridge_alive})

    def _safe_call(self, call, extra: dict | None = None) -> dict[str, Any]:
        """Выполнить операцию с ПЧ, завернув ошибки в dict-ответ."""
        vfd = self._get_vfd()
        if vfd is None:
            return {"status": "error", "message": "мост недоступен: владелец robot_io не стартовал"}
        if not vfd.is_connected:
            return {"status": "error", "message": "робот (мост) не подключён"}
        try:
            result = call(vfd)
        except (ModbusDriverError, VfdFrequencyError) as exc:
            self._set_error(str(exc))
            return {"status": "error", "message": str(exc), **(extra or {})}
        payload = result if isinstance(result, dict) else {}
        return {"status": "ok", **(extra or {}), **payload}
