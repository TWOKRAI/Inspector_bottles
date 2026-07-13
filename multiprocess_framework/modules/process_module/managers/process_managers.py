"""
Управление менеджерами процесса.

Создание менеджеров и возврат ManagersBundle (ADR-PM-009: return-based composition).
Composition-объект ЧИТАЕТ из process, но НЕ ПИШЕТ в его атрибуты.
Lazy imports в методах создания менеджеров.
"""

from typing import Any, Dict

from ..types import ManagersBundle


class ProcessManagers:
    """
    Управление менеджерами процесса.

    Инкапсулирует логику создания менеджеров.
    Зависимости передаются через process (DI-контейнер).

    Контракт: создаёт менеджеры и возвращает ManagersBundle.
    ProcessModule сам присваивает атрибуты из bundle (ADR-PM-009).
    """

    def __init__(self, process):
        """
        Args:
            process: Ссылка на ProcessModule
        """
        self.process = process

    def create_all(self) -> ManagersBundle:
        """Создать все менеджеры процесса и вернуть bundle.

        Порядок создания менеджеров определён зависимостями:
        worker → logger → error → router(нужен logger) →
        stats(нужен logger) → command(нужен logger, stats) → console.

        Returns:
            ManagersBundle — контейнер созданных менеджеров.
        """
        managers_config = self.process.config_handler.get_managers_config()

        worker = self._create_worker_manager()
        logger = self._create_logger_manager(managers_config)
        error = self._create_error_manager(managers_config)
        router = self._create_router_manager(managers_config, logger=logger)
        stats = self._create_stats_manager(managers_config, logger=logger)
        command = self._create_command_manager(
            managers_config,
            logger=logger,
            stats=stats,
        )
        console, console_enabled = self._create_console_manager(managers_config)

        return ManagersBundle(
            worker=worker,
            logger=logger,
            router=router,
            command=command,
            stats=stats,
            console=console,
            error=error,
            config_manager=self.process.config_manager,
            console_enabled=console_enabled,
        )

    def register_all(self, bundle: ManagersBundle, process) -> None:
        """Зарегистрировать менеджеры из bundle через ObservableMixin.

        Args:
            bundle: ManagersBundle с созданными менеджерами.
            process: ProcessModule — хост (владелец атрибутов).
        """
        process.register_manager("worker", bundle.worker, enabled=True)
        process.register_manager("logger", bundle.logger, enabled=True)
        process.register_manager("stats", bundle.stats, enabled=True)
        process.register_manager("command", bundle.command, enabled=True)
        process.register_manager("router", bundle.router, enabled=True)
        process.register_manager("console", bundle.console, enabled=bundle.console_enabled)
        if bundle.error is not None:
            # Task 5.14: каноничное имя error-гнезда — "error" (совпадает с
            # ObservableMixin._track_error, которое пробует именно "error").
            process.register_manager("error", bundle.error, enabled=True)

    def attach_adapters(self, bundle: ManagersBundle, process) -> None:
        """Создать адаптеры и привязать их к менеджерам.

        Args:
            bundle: ManagersBundle с созданными менеджерами.
            process: ProcessModule — хост (передаётся в адаптеры).
        """
        from ...command_module import CommandAdapter
        from ...console_module.adapters.console_adapter import ConsoleAdapter
        from ...logger_module.adapters.logger_adapter import LoggerAdapter
        from ...router_module import RouterAdapter
        from ...statistics_module import StatsAdapter
        from ...worker_module.adapters.worker_adapter import WorkerAdapter

        worker_adapter = WorkerAdapter(bundle.worker, process)
        logger_adapter = LoggerAdapter(bundle.logger, process)
        stats_adapter = StatsAdapter(bundle.stats, process)
        command_adapter = CommandAdapter(bundle.command, process)
        router_adapter = RouterAdapter(bundle.router, process)
        console_adapter = ConsoleAdapter(bundle.console, process)

        bundle.worker.attach_adapter(worker_adapter, name="process")
        bundle.logger.attach_adapter(logger_adapter, name="process")
        bundle.stats.attach_adapter(stats_adapter, name="process")
        bundle.command.attach_adapter(command_adapter, name="process")
        bundle.router.attach_adapter(router_adapter, name="process")
        bundle.console.attach_adapter(console_adapter, name="process")

        stats_adapter.setup()
        console_adapter.setup()

    def connect_event_manager(self, process) -> None:
        """Подключить event_manager из shared_resources к router_manager.

        Вызывается после _apply_managers_bundle, когда process.router_manager уже назначен.

        Args:
            process: ProcessModule с назначенным router_manager.
        """
        if (
            process.shared_resources
            and hasattr(process.shared_resources, "event_manager")
            and process.shared_resources.event_manager
        ):
            process.shared_resources.event_manager.set_router_manager(process.router_manager)

    # ========================================================================
    # ПРИВАТНЫЕ МЕТОДЫ СОЗДАНИЯ МЕНЕДЖЕРОВ
    # Каждый метод ЧИТАЕТ из self.process (name, config_handler, etc.)
    # и ВОЗВРАЩАЕТ созданный менеджер. Запись в self.process.* запрещена.
    # ========================================================================

    def _create_worker_manager(self) -> Any:
        from ...worker_module import WorkerManager

        worker = WorkerManager(
            manager_name=self.process.name,
            process=self.process,
        )
        worker.initialize()
        return worker

    def _create_logger_manager(self, managers_config: Dict[str, Any]) -> Any:
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

        logger = LoggerManager(
            manager_name=f"logger_{self.process.name}",
            config=log_config,
            process=self.process,
            config_manager=self.process.config_manager,
        )
        logger.initialize()
        return logger

    def _create_error_manager(self, managers_config: Dict[str, Any]) -> Any | None:
        error_config_dict = managers_config.get("error", {})
        if isinstance(error_config_dict, dict) and error_config_dict:
            from ...error_module import ErrorManager, ErrorManagerConfig

            error_config = ErrorManagerConfig.model_validate(error_config_dict)
            error = ErrorManager(
                manager_name=f"error_{self.process.name}",
                config=error_config,
                process=self.process,
            )
            error.initialize()
            return error

        return None

    def _create_router_manager(
        self,
        managers_config: Dict[str, Any],
        logger: Any,
    ) -> Any:
        from ...router_module import RouterManager

        router_config = managers_config.get("router", {}) or {}
        duplicate_messages = router_config.get("duplicate_messages_to_logger", False)

        # Option A frame-trace: per-process snapshot последнего кадра в файл
        # (overwrite по seq_id) через LoggerManager-канал. Включается INSPECTOR_FRAME_TRACE=1.
        import os as _os

        frame_trace_on = _os.environ.get("INSPECTOR_FRAME_TRACE", "").strip().lower() in ("1", "true", "yes")

        router = RouterManager(
            manager_name=f"router_{self.process.name}",
            process=self.process,
            queue_registry=self.process.queue_registry,
            logger=logger,
            # F3 (ревью G.2): проводим декларативный флаг из router_config —
            # конфиг-путь use_kind_channels был мёртв (env/ctor только). Приоритет
            # ctor > env > конфиг разрешается в RouterManager._resolve_use_kind_channels.
            use_kind_channels_config=bool(router_config.get("use_kind_channels", False)),
        )
        router.initialize()

        if logger and (duplicate_messages or frame_trace_on):

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
                    line = " ".join(log_parts)
                    # DEBUG, не INFO: per-message дубль — основной источник «бесконечного
                    # терминала». На DEBUG он остаётся доступен в LoggerManager, но не флудит INFO.
                    if duplicate_messages:
                        logger.debug(line, module="router_messages")
                    # Frame-trace: только кадровые сообщения (с seq_id) → overwrite-канал.
                    if frame_trace_on:
                        seq = msg.get("seq_id")
                        if seq is None and isinstance(msg.get("data"), dict):
                            seq = msg["data"].get("seq_id")
                        if seq is not None:
                            logger.frame_trace(line, seq)
                except Exception:  # nosec B110 — диагностический middleware: сбой логирования не должен ронять роутинг
                    pass
                return msg

            router._send_mw.add(_log_message_middleware)

        return router

    def _create_stats_manager(
        self,
        managers_config: Dict[str, Any],
        logger: Any,
    ) -> Any:
        from ...statistics_module import StatsManager, StatsManagerConfig

        stats_config_dict = managers_config.get("stats", {})
        stats_config = StatsManagerConfig()
        if isinstance(stats_config_dict, dict):
            for key, value in stats_config_dict.items():
                if hasattr(stats_config, key):
                    setattr(stats_config, key, value)

        stats = StatsManager(
            manager_name=f"stats_{self.process.name}",
            config=stats_config,
            process=self.process,
            managers={"logger": logger},
        )
        stats.initialize()
        return stats

    def _create_command_manager(
        self,
        managers_config: Dict[str, Any],
        logger: Any,
        stats: Any,
    ) -> Any:
        from ...command_module import CommandManager

        command_config = managers_config.get("command", {})
        command = CommandManager(
            self.process.name,
            managers={
                "logger": logger,
                "stats": stats,
            },
            config={
                "logger": command_config.get("enable_logging", True),
                "stats": command_config.get("enable_statistics", True),
            },
            config_manager=self.process.config_manager,
        )
        return command

    def _create_console_manager(
        self,
        managers_config: Dict[str, Any],
    ) -> tuple[Any, bool]:
        """Создать ConsoleManager.

        Returns:
            tuple(console_manager, console_enabled)
        """
        from ...console_module import ConsoleManager
        from ...console_module.configs.console_config import ConsoleConfig

        console_cfg_dict = managers_config.get("console", {})
        console_config = (
            ConsoleConfig(**console_cfg_dict)
            if isinstance(console_cfg_dict, dict) and console_cfg_dict
            else ConsoleConfig()
        )

        console = ConsoleManager(
            manager_name=f"console_{self.process.name}",
            config=console_config,
            process=self.process,
        )
        console.initialize()

        enabled = console_config.enabled if console_config is not None else False
        return console, enabled
