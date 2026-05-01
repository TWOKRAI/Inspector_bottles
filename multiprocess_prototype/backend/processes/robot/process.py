"""RobotProcess — инфраструктурный контейнер для RobotService.

Тонкий ProcessModule: управление воркерами, IPC.
Команды — в commands.py, адаптер — в adapter.py.
"""
from __future__ import annotations

import time

from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig
from multiprocess_prototype.services.robot.service import RobotService

from .adapter import RobotAdapter
from .commands import build_command_table


class RobotProcess(ProcessModule):
    """Процесс робота отбраковки. Инфраструктура: воркеры, IPC, команды."""

    def _init_system_threads(self):
        pass

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._service = None

    def _init_application_threads(self) -> None:
        self._log_info("RobotProcess initializing...")
        adapter = RobotAdapter(self)
        log_file = self.get_config("log_file", "./robot_actions.log")
        reject_delay = self.get_config("reject_delay", 0.5)

        self._service = RobotService(output=adapter, reject_delay=reject_delay)
        self._log_file = log_file

        # Команды из таблицы
        cmd_table = build_command_table(self._service)
        for cmd, handler in cmd_table.items():
            self.command_manager.register_command(cmd, handler)

        # StateProxy для записи state (без подписок на config — Robot только команды)
        from multiprocess_framework.modules.state_store_module import StateProxy

        self._state_proxy = StateProxy(
            "robot",
            router=self.router_manager,
            server_target="ProcessManager",
        )

        # Регистрация обработчика state.changed
        self.router_manager.register_message_handler("state.changed", self._state_proxy.on_state_changed)

        # Начальная запись state
        self._state_proxy.set("robot.state.status", "initialized")

        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker(
            "robot_worker", self._robot_worker, cfg, auto_start=True
        )
        self._log_info(f"RobotProcess ready: log_file={log_file}")

    # --- Воркер ---

    def _robot_worker(self, stop_event, pause_event) -> None:
        """Воркер: слушает system-канал для команд."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue
            msgs = self.receive(timeout=0.1, channel_types=["system"])
            for msg in msgs:
                msg_dict = (
                    msg
                    if isinstance(msg, dict)
                    else (msg.to_dict() if hasattr(msg, "to_dict") else None)
                )
                if msg_dict and msg_dict.get("command") and self.command_manager:
                    try:
                        self.command_manager.handle_command(msg_dict)
                    except Exception as e:
                        self._log_error(f"Command '{msg_dict.get('command')}' failed: {e}")
            time.sleep(0.02)

    # --- Shutdown ---

    def shutdown(self) -> bool:
        action_count = self._service.action_count if self._service else 0
        self._log_info(f"RobotProcess shutting down. Total actions: {action_count}")
        if hasattr(self, "_state_proxy"):
            self._state_proxy.set("robot.state.status", "shutdown")
            self._state_proxy.set("robot.state.action_count", action_count)
            self._state_proxy.shutdown()
        self.is_initialized = False
        return super().shutdown()
