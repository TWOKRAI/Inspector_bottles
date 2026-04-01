"""
ConsoleAdapter — связывает ConsoleManager с LoggerManager и CommandManager.

setup() вызывается один раз после инициализации всех менеджеров процесса:
  1. Если console enabled  → добавляет ConsoleLogChannel в LoggerManager
  2. Если console interactive → запускает input loop с callback в CommandManager
"""
from typing import Any, Optional

from ...base_manager.adapters.base_adapter import BaseAdapter
from ..interfaces import IConsoleManager
from ..configs.console_config import ConsoleConfig


class ConsoleAdapter(BaseAdapter):
    """Адаптер интеграции ConsoleManager с остальными менеджерами процесса."""

    def __init__(
        self,
        console_manager: IConsoleManager,
        process: Optional[Any] = None,
        adapter_name: str = "ConsoleAdapter",
    ) -> None:
        super().__init__(
            manager=console_manager,
            process=process,
            adapter_name=adapter_name,
        )
        self._console = console_manager
        self._console_log_channel = None

    # -------------------------------------------------------------------------
    # BaseAdapter
    # -------------------------------------------------------------------------

    def setup(self) -> bool:
        """Связать ConsoleManager с LoggerManager и CommandManager."""
        try:
            config: ConsoleConfig = getattr(self._console, "_config", ConsoleConfig())

            # 1. ConsoleLogChannel в LoggerManager
            if config.enabled and self.process and getattr(self.process, "logger_manager", None):
                from ..channels.console_log_channel import ConsoleLogChannel
                self._console_log_channel = ConsoleLogChannel(self._console)
                logger = self.process.logger_manager
                if hasattr(logger, "register_channel"):
                    logger.register_channel(self._console_log_channel)
                    self._log("info", "ConsoleLogChannel registered in LoggerManager")

            # 2. Input loop → CommandManager
            if config.interactive and self.process and getattr(self.process, "command_manager", None):
                cmd_mgr = self.process.command_manager

                def _on_input(text: str) -> None:
                    try:
                        cmd_mgr.handle_command({
                            "command": text,
                            "source": "console",
                            "process": getattr(self.process, "name", "unknown"),
                        })
                    except Exception as exc:
                        self._log("error", f"Command handling error: {exc}")

                self._console.enable_input(_on_input)
                self._log("info", "Interactive input loop started")

            self._initialized = True
            return True

        except Exception as exc:
            self._log("error", f"ConsoleAdapter setup failed: {exc}")
            return False

    def is_initialized(self) -> bool:
        return self._initialized
