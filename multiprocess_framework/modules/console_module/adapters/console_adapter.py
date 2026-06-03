"""
ConsoleAdapter — связывает ConsoleManager с LoggerManager и CommandManager.

setup() вызывается один раз после инициализации всех менеджеров процесса:
  1. Если console enabled  → добавляет ConsoleLogChannel в LoggerManager
  2. Если console interactive → запускает input loop с callback в CommandManager
  3. Регистрирует встроенные команды (reg) в CommandManager
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
        self._register_command_handler = None

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
                    """Парсинг raw-текста в message с command + args."""
                    try:
                        parts = text.strip().split()
                        if not parts:
                            return
                        command = parts[0]
                        args = parts[1:]
                        result = cmd_mgr.handle_command(
                            {
                                "command": command,
                                "args": args,
                                "raw": text,
                                "source": "console",
                                "process": getattr(self.process, "name", "unknown"),
                            }
                        )
                        # Если обработчик вернул строку, выводим в консоль
                        if isinstance(result, str) and result:
                            self._console.write(result + "\n")
                    except Exception as exc:
                        self._log("error", f"Command handling error: {exc}")

                self._console.enable_input(_on_input)
                self._log("info", "Interactive input loop started")

                # 3. Регистрация встроенных команд
                self._register_builtin_commands(cmd_mgr)

            self._initialized = True
            return True

        except Exception as exc:
            self._log("error", f"ConsoleAdapter setup failed: {exc}")
            return False

    def is_initialized(self) -> bool:
        return self._initialized

    # -------------------------------------------------------------------------
    # Builtin commands
    # -------------------------------------------------------------------------

    def _register_builtin_commands(self, cmd_mgr: Any) -> None:
        """Зарегистрировать встроенные консольные команды в CommandManager."""
        # reg -- работа с регистрами
        registers_mgr = getattr(self.process, "registers_manager", None)
        router_mgr = getattr(self.process, "router_manager", None)

        from ..commands.register_commands import RegisterCommandHandler
        from ..commands.system_commands import SystemCommandHandler

        self._register_command_handler = RegisterCommandHandler(
            registers_manager=registers_mgr,
            router_manager=router_mgr,
        )
        cmd_mgr.register_command(
            "reg",
            self._register_command_handler.handle,
            expects_full_message=True,
            metadata={"description": "Register commands (list/get/set/info)"},
            tags=["console", "registers"],
        )
        self._log("info", "Builtin command 'reg' registered")

        # Системные команды -- help, status, ps, stats
        self._system_command_handler = SystemCommandHandler(process_info=self.process)

        def _cmd_help(msg: Any) -> str:
            registry: Optional[dict] = None
            if hasattr(cmd_mgr, "get_commands"):
                try:
                    registry = {
                        cmd.get("key", ""): cmd.get("description", "")
                        for cmd in cmd_mgr.get_commands()
                        if isinstance(cmd, dict)
                    }
                except Exception:
                    pass
            return self._system_command_handler.help(registry)

        def _cmd_status(msg: Any) -> str:
            return self._system_command_handler.status(self.process)

        def _cmd_ps(msg: Any) -> str:
            process_mgr = getattr(self.process, "process_manager", None)
            return self._system_command_handler.ps(process_mgr)

        def _cmd_stats(msg: Any) -> str:
            stats_mgr = getattr(self.process, "stats_manager", None)
            return self._system_command_handler.stats(stats_mgr)

        for name, fn, description in [
            ("help", _cmd_help, "Show available commands and descriptions"),
            ("status", _cmd_status, "Show current process state (name, pid, managers)"),
            ("ps", _cmd_ps, "List child processes"),
            ("stats", _cmd_stats, "Show aggregated metrics"),
        ]:
            cmd_mgr.register_command(
                name,
                fn,
                expects_full_message=True,
                metadata={"description": description},
                tags=["console", "system"],
            )
        self._log("info", "Builtin system commands registered: help, status, ps, stats")
