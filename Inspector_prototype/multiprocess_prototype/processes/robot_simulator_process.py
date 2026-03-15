"""
RobotSimulatorProcess — имитация робота-отбраковщика.

Получает COMMAND reject_item от Renderer, логирует frame_id, center, area в файл.
Использует CommandManager для обработки команд (command_module).
"""

import datetime
import time

from multiprocess_framework.refactored.modules.process_module import ProcessModule
from multiprocess_framework.refactored.modules.worker_module import (
    ThreadConfig,
    ExecutionMode,
)


class RobotSimulatorProcess(ProcessModule):
    """Процесс-симулятор робота. Логирует отбраковку в файл."""

    def _init_system_threads(self):
        """Robot получает команды в воркере из system-очереди — system_thread не нужен."""
        pass

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._action_count = 0

    def _init_application_threads(self):
        """Инициализация RobotSimulatorProcess: команда reject_item, воркер robot_worker."""
        self._log_info("RobotSimulatorProcess initializing...")

        self._log_file = self.get_config("log_file", "./robot_actions.log")
        self._reject_delay = self.get_config("reject_delay", 0.5)

        self.command_manager.register_command("reject_item", self._cmd_reject)

        config = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker(
            "robot_worker", self._robot_worker, config, auto_start=True
        )

        self._log_info(f"RobotSimulatorProcess ready: log_file={self._log_file}")

    def _cmd_reject(self, data):
        """Обработчик команды отбраковки от Renderer."""
        frame_id = data.get("frame_id", 0)
        defects = data.get("defects", [])

        for defect in defects:
            self._action_count += 1
            center = defect.get("center", [0, 0])
            area = defect.get("area", 0)
            self._log_info(
                f"REJECT #{self._action_count}: frame={frame_id}, "
                f"pos=({center[0]}, {center[1]}), area={area}"
            )
            self._write_to_log(frame_id, center, area)

        if self._reject_delay > 0:
            time.sleep(self._reject_delay)

        return {"status": "ok", "action_id": self._action_count}

    def _robot_worker(self, stop_event, pause_event):
        """Цикл приёма сообщений → вызов command_manager.handle_command."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            msgs = self.receive(timeout=0.1, channel_types=['system'])
            for msg in msgs:
                if isinstance(msg, dict):
                    msg_dict = msg
                elif hasattr(msg, "to_dict"):
                    msg_dict = msg.to_dict()
                else:
                    continue

                cmd = msg_dict.get("command")
                if cmd and self.command_manager:
                    try:
                        self.command_manager.handle_command(msg_dict)
                    except Exception as e:
                        self._log_error(f"Command '{cmd}' failed: {e}")

            time.sleep(0.02)

    def _write_to_log(self, frame_id: int, center: list, area: int) -> None:
        """Запись действия робота в файл."""
        ts = datetime.datetime.now().isoformat()
        line = f"{ts} | frame={frame_id} | x={center[0]} y={center[1]} | area={area}\n"
        try:
            with open(self._log_file, "a") as f:
                f.write(line)
        except Exception as e:
            self._log_error(f"Failed to write robot log: {e}")

    def shutdown(self) -> bool:
        self._log_info(
            f"RobotSimulatorProcess shutting down. Total actions: {self._action_count}"
        )
        self.is_initialized = False
        return super().shutdown()
