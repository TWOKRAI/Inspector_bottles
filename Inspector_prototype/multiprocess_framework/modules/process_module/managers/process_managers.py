"""
Управление менеджерами процесса.

Инициализация и управление менеджерами через ObservableMixin.
Lazy imports в методах создания менеджеров.
"""

from typing import Any, Dict


class ProcessManagers:
    """
    Управление менеджерами процесса.

    Инкапсулирует логику создания и регистрации менеджеров.
    Зависимости передаются через process (DI-контейнер).
    """

    def __init__(self, process):
        """
        Args:
            process: Ссылка на ProcessModule
        """
        self.process = process

    def initialize(self):
        """Инициализация менеджеров процесса через ObservableMixin."""
        managers_config = self.process.config_handler.get_managers_config()
        self._create_worker_manager()
        self._create_logger_manager(managers_config)
        self._create_error_manager(managers_config)
        self._create_router_manager(managers_config)
        self._create_stats_manager(managers_config)
        self._create_command_manager(managers_config)
        console_config = self._create_console_manager(managers_config)
        self._register_all_managers(console_config)
        self._attach_all_adapters()
        self._connect_event_manager()

    def _create_worker_manager(self) -> None:
        from ...worker_module import WorkerManager

        self.process.worker_manager = WorkerManager(
            manager_name=self.process.name,
            process=self.process,
        )
        self.process.worker_manager.initialize()

    def _create_logger_manager(self, managers_config: Dict[str, Any]) -> None:
        from ...logger_module import LoggerManager, LoggerManagerConfig

        logger_config = managers_config.get("logger", {})
        if isinstance(logger_config, dict):
            merged = {
                **logger_config,
                "app_name": logger_config.get("app_name", self.process.name),
            }
            log_config = LoggerManagerConfig.model_validate(merged)
        else:
            log_config = LoggerManagerConfig(app_name=self.process.name)

        self.process.logger_manager = LoggerManager(
            manager_name=f"logger_{self.process.name}",
            config=log_config,
            process=self.process,
            config_manager=self.process.config_manager,
            enable_router_routing=True,
        )
        self.process.logger_manager.initialize()

    def _create_error_manager(self, managers_config: Dict[str, Any]) -> None:
        error_config_dict = managers_config.get("error", {})
        if isinstance(error_config_dict, dict) and error_config_dict:
            from ...error_module import ErrorManager, ErrorManagerConfig

            error_config = ErrorManagerConfig.model_validate(error_config_dict)

            self.process.error_manager = ErrorManager(
                manager_name=f"error_{self.process.name}",
                config=error_config,
                process=self.process,
            )
            self.process.error_manager.initialize()
            self.process.register_manager(
                "errors", self.process.error_manager, enabled=True
            )
        else:
            self.process.error_manager = None

    def _create_router_manager(self, managers_config: Dict[str, Any]) -> None:
        from ...router_module import RouterManager

        router_config = managers_config.get("router", {}) or {}
        duplicate_messages = router_config.get("duplicate_messages_to_logger", False)

        router_manager = RouterManager(
            manager_name=f"router_{self.process.name}",
            process=self.process,
            queue_registry=self.process.queue_registry,
            logger=self.process.logger_manager,
        )
        router_manager.initialize()

        if duplicate_messages and self.process.logger_manager:

            def _log_message_middleware(msg):
                try:
                    log_parts = [
                        msg.get("type", "?"),
                        msg.get("sender", "?"),
                        "->",
                        str(msg.get("targets", [])),
                    ]
                    if msg.get("data_type"):
                        log_parts.append(f" data_type={msg.get('data_type')}")
                    if msg.get("command"):
                        log_parts.append(f" cmd={msg.get('command')}")
                    if msg.get("event_type"):
                        log_parts.append(f" event={msg.get('event_type')}")
                    self.process.logger_manager.info(
                        " ".join(log_parts),
                        module="router_messages",
                    )
                except Exception:
                    pass
                return msg

            router_manager._send_mw.add(_log_message_middleware)

        self.process.router_manager = router_manager

    def _create_stats_manager(self, managers_config: Dict[str, Any]) -> None:
        from ...statistics_module import StatsManager, StatsManagerConfig

        stats_config_dict = managers_config.get("stats", {})
        stats_config = StatsManagerConfig()
        if isinstance(stats_config_dict, dict):
            for key, value in stats_config_dict.items():
                if hasattr(stats_config, key):
                    setattr(stats_config, key, value)

        self.process.stats_manager = StatsManager(
            manager_name=f"stats_{self.process.name}",
            config=stats_config,
            process=self.process,
            router_manager=self.process.router_manager,
            managers={"logger": self.process.logger_manager},
        )
        self.process.stats_manager.initialize()

    def _create_command_manager(self, managers_config: Dict[str, Any]) -> None:
        from ...command_module import CommandManager

        command_config = managers_config.get("command", {})
        self.process.command_manager = CommandManager(
            self.process.name,
            managers={
                "logger": self.process.logger_manager,
                "stats": self.process.stats_manager,
            },
            config={
                "logger": command_config.get("enable_logging", True),
                "stats": command_config.get("enable_statistics", True),
            },
            config_manager=self.process.config_manager,
        )

    def _create_console_manager(self, managers_config: Dict[str, Any]):
        from ...console_module import ConsoleManager
        from ...console_module.configs.console_config import ConsoleConfig

        console_cfg_dict = managers_config.get("console", {})
        console_config = ConsoleConfig(**console_cfg_dict) if isinstance(console_cfg_dict, dict) and console_cfg_dict else ConsoleConfig()

        self.process.console_manager = ConsoleManager(
            manager_name=f"console_{self.process.name}",
            config=console_config,
            process=self.process,
        )
        self.process.console_manager.initialize()
        return console_config

    def _register_all_managers(self, console_config) -> None:
        enabled = console_config.enabled if console_config is not None else False

        self.process.register_manager(
            "worker", self.process.worker_manager, enabled=True
        )
        self.process.register_manager(
            "logger", self.process.logger_manager, enabled=True
        )
        self.process.register_manager(
            "stats", self.process.stats_manager, enabled=True
        )
        self.process.register_manager(
            "command", self.process.command_manager, enabled=True
        )
        self.process.register_manager(
            "router", self.process.router_manager, enabled=True
        )
        self.process.register_manager(
            "console", self.process.console_manager, enabled=enabled
        )

    def _attach_all_adapters(self) -> None:
        from ...command_module import CommandAdapter
        from ...console_module.adapters.console_adapter import ConsoleAdapter
        from ...logger_module.adapters.logger_adapter import LoggerAdapter
        from ...router_module import RouterAdapter
        from ...statistics_module import StatsAdapter
        from ...worker_module.adapters.worker_adapter import WorkerAdapter

        worker_adapter = WorkerAdapter(self.process.worker_manager, self.process)
        logger_adapter = LoggerAdapter(self.process.logger_manager, self.process)
        stats_adapter = StatsAdapter(self.process.stats_manager, self.process)
        command_adapter = CommandAdapter(self.process.command_manager, self.process)
        router_adapter = RouterAdapter(self.process.router_manager, self.process)
        console_adapter = ConsoleAdapter(self.process.console_manager, self.process)

        self.process.worker_manager.attach_adapter(worker_adapter, name="process")
        self.process.logger_manager.attach_adapter(logger_adapter, name="process")
        self.process.stats_manager.attach_adapter(stats_adapter, name="process")
        self.process.command_manager.attach_adapter(command_adapter, name="process")
        self.process.router_manager.attach_adapter(router_adapter, name="process")
        self.process.console_manager.attach_adapter(console_adapter, name="process")
        stats_adapter.setup()
        console_adapter.setup()

    def _connect_event_manager(self) -> None:
        if (
            self.process.shared_resources
            and hasattr(self.process.shared_resources, "event_manager")
            and self.process.shared_resources.event_manager
        ):
            self.process.shared_resources.event_manager.set_router_manager(
                self.process.router_manager
            )

    def register_manager(self, name: str, manager, enabled: bool = True):
        """Регистрация менеджера (делегирование к ObservableMixin)."""
        self.process.register_manager(name, manager, enabled=enabled)

    def get_manager(self, name: str):
        """Получение менеджера по имени (делегирование к ObservableMixin)."""
        return self.process.get_manager(name)
