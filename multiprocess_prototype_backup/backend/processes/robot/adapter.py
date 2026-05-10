"""RobotAdapter — IPC/file facade для RobotService."""
from __future__ import annotations

from multiprocess_framework.modules.process_module import ProcessIO


class RobotAdapter:
    """Реализует RobotOutputPort: запись в log-файл + логи через ProcessIO."""

    def __init__(self, process) -> None:
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
