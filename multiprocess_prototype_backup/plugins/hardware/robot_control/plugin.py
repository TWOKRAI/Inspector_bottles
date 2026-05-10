"""RobotPlugin — управление роботом-отбраковщиком.

Output-плагин: принимает команды reject/pass → управляет оборудованием.
Простейший плагин — только сервис + команды + воркер.
"""

from __future__ import annotations

import time

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.registry import register_plugin
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig
from multiprocess_prototype.backend.processes.robot.adapter import RobotAdapter
from multiprocess_prototype.backend.processes.robot.commands import build_command_table
from multiprocess_prototype.services.robot.service import RobotService


@register_plugin("robot", category="output", description="Управление роботом-отбраковщиком")
class RobotPlugin(ProcessModulePlugin):
    """Управление роботом-отбраковщиком."""

    name = "robot"
    category = "output"
    inputs = []
    outputs = []
    commands = {}  # регистрация вручную

    def configure(self, ctx: PluginContext) -> None:
        """IDLE → READY: сервис, команды, StateProxy, воркер."""
        self._ctx = ctx
        cfg = ctx.config

        adapter = RobotAdapter(ctx._process)
        reject_delay = cfg.get("reject_delay", 0.5)
        self._service = RobotService(output=adapter, reject_delay=reject_delay)

        # Команды
        cmd_table = build_command_table(self._service)
        for cmd, handler in cmd_table.items():
            ctx.command_manager.register_command(cmd, handler)

        # StateProxy
        from multiprocess_framework.modules.state_store_module import StateProxy

        self._state_proxy = StateProxy(
            "robot",
            router=ctx.router_manager,
            server_target="ProcessManager",
        )
        ctx.router_manager.register_message_handler(
            "state.changed", self._state_proxy.on_state_changed
        )

        # Воркер для обработки system-канала
        worker_cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker(
            "robot_worker", self._robot_worker, worker_cfg, auto_start=True
        )

        ctx.log_info(f"RobotPlugin configured (reject_delay={reject_delay})")

    def start(self, ctx: PluginContext) -> None:
        """READY → RUNNING: начальный state."""
        self._state_proxy.set("robot.state.status", "initialized")
        ctx.log_info("RobotPlugin ready")

    def shutdown(self, ctx: PluginContext) -> None:
        """* → STOPPED."""
        action_count = self._service.action_count if self._service else 0
        ctx.log_info(f"RobotPlugin shutting down. Total actions: {action_count}")
        if hasattr(self, "_state_proxy"):
            self._state_proxy.set("robot.state.status", "shutdown")
            self._state_proxy.set("robot.state.action_count", action_count)
            self._state_proxy.shutdown()

    # --- Воркер ---

    def _robot_worker(self, stop_event, pause_event) -> None:
        """Воркер: слушает system-канал для команд."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue
            msgs = self._ctx._process.receive(timeout=0.1, channel_types=["system"])
            for msg in msgs:
                msg_dict = (
                    msg
                    if isinstance(msg, dict)
                    else (msg.to_dict() if hasattr(msg, "to_dict") else None)
                )
                if msg_dict and msg_dict.get("command") and self._ctx.command_manager:
                    try:
                        self._ctx.command_manager.handle_command(msg_dict)
                    except Exception as e:
                        self._ctx.log_error(f"Command '{msg_dict.get('command')}' failed: {e}")
            time.sleep(0.02)
