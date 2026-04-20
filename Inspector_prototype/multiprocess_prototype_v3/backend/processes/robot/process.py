"""RobotProcess — инфраструктурный контейнер для RobotService."""
from __future__ import annotations

import time

from multiprocess_framework.modules.process_module import ProcessIO, ProcessModule
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig
from multiprocess_prototype_v3.services.robot.service import RobotService


class RobotProcess(ProcessModule):
    """Процесс робота отбраковки. Инфраструктура: воркеры, IPC, команды."""

    def _init_system_threads(self):
        pass

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._service = None

    def _init_application_threads(self) -> None:
        self._log_info("RobotProcess initializing...")
        adapter = _RobotAdapter(self)
        log_file = self.get_config("log_file", "./robot_actions.log")
        reject_delay = self.get_config("reject_delay", 0.5)

        self._service = RobotService(output=adapter, reject_delay=reject_delay)
        self._log_file = log_file

        self.command_manager.register_command("reject_item", self._cmd_reject)

        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker(
            "robot_worker", self._robot_worker, cfg, auto_start=True
        )
        self._log_info(f"RobotProcess ready: log_file={log_file}")

    def _cmd_reject(self, data: dict) -> dict:
        """Команда отбраковки — делегация в сервис."""
        result = self._service.process_rejection(
            frame_id=data.get("frame_id", 0),
            defects=data.get("defects", []),
        )
        if self._service.reject_delay > 0:
            time.sleep(self._service.reject_delay)
        return result

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

    def shutdown(self) -> bool:
        action_count = self._service.action_count if self._service else 0
        self._log_info(f"RobotProcess shutting down. Total actions: {action_count}")
        self.is_initialized = False
        return super().shutdown()


class _RobotAdapter:
    """Реализует RobotOutputPort: запись в log-файл + логи через ProcessIO."""

    def __init__(self, process: RobotProcess) -> None:
        self._p = process  # нужен для get_config (log_file path)
        self._io = ProcessIO(process)
        self._log_file = None

    def _get_log_file(self) -> str:
        if self._log_file is None:
            self._log_file = self._p.get_config("log_file", "./robot_actions.log")
        return self._log_file

    def write_log(self, text: str) -> None:
        """Записать action-лог в файл на диске (не IPC)."""
        try:
            with open(self._get_log_file(), "a") as f:
                f.write(text)
        except Exception as e:
            self._io.log_error(f"Failed to write robot log: {e}")

    def log_info(self, text: str) -> None:
        self._io.log_info(text)

    def log_error(self, text: str) -> None:
        self._io.log_error(text)
