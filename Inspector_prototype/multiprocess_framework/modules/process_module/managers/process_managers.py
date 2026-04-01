"""
Управление менеджерами процесса.

Инициализация и управление менеджерами через ObservableMixin.
Lazy imports перенесены в начало файла для ясности зависимостей.
"""

from typing import Dict, Any


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
        from ...worker_module import WorkerManager
        from ...worker_module.adapters.worker_adapter import WorkerAdapter
        from ...router_module import RouterManager, RouterAdapter
        from ...command_module import CommandManager, CommandAdapter
        from ...logger_module import LoggerManager, LoggerManagerConfig
        from ...logger_module.adapters.logger_adapter import LoggerAdapter

        managers_config = self.process.config_handler.get_managers_config()

        # 1. WorkerManager
        self.process.worker_manager = WorkerManager(
            manager_name=self.process.name,
            process=self.process,
        )
        self.process.worker_manager.initialize()

        # 2. LoggerManager
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

        # 2b. ErrorManager (опционально, если есть конфиг)
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
            self.process.register_manager("errors", self.process.error_manager, enabled=True)
        else:
            self.process.error_manager = None

        # 3. RouterManager
        router_config = managers_config.get("router", {}) or {}
        duplicate_messages = router_config.get("duplicate_messages_to_logger", False)

        router_manager = RouterManager(
            manager_name=f"router_{self.process.name}",
            process=self.process,
            queue_registry=self.process.queue_registry,
            logger=self.process.logger_manager,
        )
        router_manager.initialize()

        # Дублирование сообщений в LoggerManager для отладки (messages.log)
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

        # 4. StatsManager
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

        # 5. CommandManager
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

        # 6. ConsoleManager (disabled по умолчанию)
        from ...console_module import ConsoleManager
        from ...console_module.configs.console_config import ConsoleConfig
        from ...console_module.adapters.console_adapter import ConsoleAdapter

        console_cfg_dict = managers_config.get("console", {})
        console_config = ConsoleConfig()
        if isinstance(console_cfg_dict, dict):
            for key, value in console_cfg_dict.items():
                if hasattr(console_config, key):
                    setattr(console_config, key, value)

        self.process.console_manager = ConsoleManager(
            manager_name=f"console_{self.process.name}",
            config=console_config,
            process=self.process,
        )
        self.process.console_manager.initialize()

        # Регистрируем менеджеры через ObservableMixin
        self.process.register_manager("worker", self.process.worker_manager, enabled=True)
        self.process.register_manager("logger", self.process.logger_manager, enabled=True)
        self.process.register_manager("stats", self.process.stats_manager, enabled=True)
        self.process.register_manager("command", self.process.command_manager, enabled=True)
        self.process.register_manager("router", self.process.router_manager, enabled=True)
        self.process.register_manager("console", self.process.console_manager, enabled=console_config.enabled)

        # Создаём и прикрепляем адаптеры
        from ...statistics_module import StatsAdapter

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

        # Обновляем EventManager в shared_resources с router_manager
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

    def reload_manager(self, manager_name: str) -> bool:
        """Пересоздать менеджер на основе текущей конфигурации."""
        try:
            self.process._log_info(f"Reloading manager '{manager_name}'")
            return True
        except Exception as e:
            self.process._log_error(f"Failed to reload manager '{manager_name}': {e}")
            return False
