"""
Базовый класс для всех процессов системы (Refactored).

Наследуется от BaseManager и использует ObservableMixin для логирования и мониторинга.
Все процессы теперь являются менеджерами с единым интерфейсом.
"""

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...state_store_module.interfaces import IStateProxy

from ...base_manager import BaseManager, ObservableMixin
from ..communication import ProcessCommunication

# Публичные контракты и типы
from ..interfaces import IProcessModule, ISharedResources

# Импорт компонентов процесса
from ..lifecycle import ProcessLifecycle
from ..managers import ProcessManagers
from ..state import ProcessState
from ..threads import SystemThreads
from ..types import ProcessStatus


class ProcessModule(BaseManager, ObservableMixin, IProcessModule):
    """
    Базовый класс для всех процессов системы (Refactored).

    Наследуется от BaseManager и использует ObservableMixin для:
    - Единообразия со всеми менеджерами системы
    - Автоматического логирования через ObservableMixin
    - Стандартного жизненного цикла (initialize/shutdown)

    Реализует IProcessModule — публичный контракт для внешних модулей.
    Принимает shared_resources через DI (ISharedResources protocol) —
    нет прямого импорта из shared_resources_module.

    Attributes:
        name: Имя процесса (синоним manager_name)
        shared_resources: ISharedResources (DI — получается снаружи)
        config: Конфигурация процесса
        queues: Словарь очередей для коммуникации
        config_handler: ProcessConfigHandler для работы с конфигурацией
        communication: ProcessCommunication для межпроцессной коммуникации
    """

    def __init__(
        self,
        name: str,
        shared_resources: ISharedResources | None = None,
        config: dict | None = None,
        state_proxy: "IStateProxy | None" = None,
    ):
        """
        Инициализация процесса.

        Args:
            name: Имя процесса
            shared_resources: ISharedResources (DI — передаётся снаружи, не импортируется)
            config: Локальная конфигурация процесса (опционально)
            state_proxy: IStateProxy (ADR-SS-006) — если передан, handler state.changed
                         регистрируется автоматически после initialize().
        """
        BaseManager.__init__(self, manager_name=name, process=None)

        ObservableMixin.__init__(
            self,
            managers={},
            config={},
            auto_proxy=True,
        )

        self.name = name
        self.shared_resources: ISharedResources | None = shared_resources
        self.config = config or {}
        self.state_proxy: "IStateProxy | None" = state_proxy

        # Компоненты (настраиваются в initialize())
        self.config_handler = None
        self.config_manager = None
        self.communication = None
        self.queues = None
        self.queue_registry = None
        self.memory_manager = None

        self._stop_requested = False

        # Текущий статус процесса для трансляции в heartbeat
        # Обновляется командами worker.pause_all / worker.resume_all
        self._current_process_status: str = "running"

        # Менеджеры (создаются в initialize() через ManagersBundle, ADR-PM-009)
        self.worker_manager = None
        self.logger_manager = None
        self.error_manager = None
        self.command_manager = None
        self.router_manager = None
        self.stats_manager = None
        self.console_manager = None

        # Внутренние компоненты (композиция)
        self._lifecycle = ProcessLifecycle(self)
        self._process_managers = ProcessManagers(self)
        self._threads = SystemThreads(self)
        self._state = ProcessState(self)

        # Heartbeat и встроенные команды (создаются в run())
        self._heartbeat = None
        self._builtin_cmds = None

        # Plugin orchestrator — опциональная композиция
        # Активируется если config["plugins"] непуст (см. _init_custom_managers)
        self._orchestrator = None

        # initialize() вызывается явно после создания

    # ========================================================================
    # РЕАЛИЗАЦИЯ BaseManager - ЖИЗНЕННЫЙ ЦИКЛ
    # ========================================================================

    def initialize(self) -> bool:
        """
        Инициализация процесса — оркестратор всех шагов (ADR-PM-009).

        ProcessModule владеет своим жизненным циклом.
        Helper-объекты (lifecycle, process_managers) возвращают результаты,
        ProcessModule сам присваивает атрибуты.

        Returns:
            bool: True если инициализация успешна
        """
        try:
            # 1-2. Конфигурация и очереди
            self._init_configuration()
            self._init_queues()

            # 3. Инициализация менеджеров через ManagersBundle
            self._init_managers()

            # 4. Инициализация коммуникации
            self._init_communication()

            # 5. Регистрация состояния процесса
            self._register_process_state()

            # 6. Воркеры и кастомные менеджеры — до message_processor,
            #    чтобы register_message_handler успел зарегистрироваться
            self._init_custom_managers()
            self._init_application_threads()

            # 6b. P4.4.1 (B2): команды НЕ копируются в message_dispatcher — kind-router
            # в receive() диспатчит type=="command" напрямую в CommandManager.

            # 7. Системные потоки (message_processor) — после воркеров
            self._init_system_threads()

            # 8. Обновляем статус на "ready"
            self.update_process_state(status=ProcessStatus.READY.value)

            # 9. Контекст логирования (proc_name в extra для логов)
            logger = self.get_manager("logger")
            if logger and hasattr(logger, "push_context"):
                logger.push_context(proc_name=self.name)

            # 10. Регистрация state.changed handler (ADR-SS-006) — только в
            #     success-пути. Раньше вызов стоял в finally и при исключении
            #     ДО присвоения router_manager молча пропускался по guard'у
            #     (§11.22 comm-system): нельзя регистрировать handler на
            #     полуинициализированном процессе.
            self._init_state_proxy()

            self.is_initialized = True
            self._log_info(f"Process '{self.name}' initialized successfully")
            return True

        except Exception as e:
            import traceback as _tb

            self._log_error(f"Failed to initialize process '{self.name}': {e}")
            self._log_error(f"Traceback: {_tb.format_exc()}")
            return False

    def shutdown(self) -> bool:
        """
        Завершение работы процесса.

        Интегрирует функциональность ProcessCore:
        - Shutdown плагинов (если есть orchestrator)
        - Остановка всех потоков
        - Очистка ресурсов
        - Отключение менеджеров

        Returns:
            bool: True если завершение успешно
        """
        # Plugin shutdown (если orchestrator был создан)
        if self._orchestrator is not None:
            self._orchestrator.shutdown()

        return self._lifecycle.shutdown()

    # ========================================================================
    # ИНИЦИАЛИЗАЦИЯ КОМПОНЕНТОВ
    # ========================================================================

    def _init_configuration(self) -> None:
        """Инициализация конфигурации процесса (ADR-PM-009: return-based).

        Вызывает lifecycle helper и сам присваивает атрибуты ProcessModule.
        Имя метода сохранено для совместимости с тестами.
        """
        ch, cm, cfg = self._lifecycle.init_configuration()
        self.config_handler, self.config_manager, self.config = ch, cm, cfg

    def _init_queues(self) -> None:
        """Инициализация очередей процесса (ADR-PM-009: return-based).

        Вызывает lifecycle helper и сам присваивает атрибуты ProcessModule.
        Имя метода сохранено для совместимости с тестами.
        """
        q, qr, mm = self._lifecycle.init_queues()
        self.queues, self.queue_registry, self.memory_manager = q, qr, mm

    def _init_managers(self) -> None:
        """Инициализация менеджеров через ManagersBundle (ADR-PM-009).

        Вызывает create_all(), получает bundle, применяет через _apply_managers_bundle.
        Имя метода сохранено для совместимости с тестами.
        """
        bundle = self._process_managers.create_all()
        self._apply_managers_bundle(bundle)

    def _apply_managers_bundle(self, bundle) -> None:
        """Распаковать ManagersBundle — ProcessModule владеет своими атрибутами.

        ProcessModule сам присваивает менеджеры из bundle,
        затем регистрирует их через ObservableMixin и подключает адаптеры.
        """
        self.worker_manager = bundle.worker
        self.logger_manager = bundle.logger
        self.error_manager = bundle.error
        self.router_manager = bundle.router
        self.stats_manager = bundle.stats
        self.command_manager = bundle.command
        self.console_manager = bundle.console
        self._process_managers.register_all(bundle, self)
        self._process_managers.attach_adapters(bundle, self)
        self._process_managers.connect_event_manager(self)

    def _init_communication(self):
        """Инициализация коммуникации процесса."""
        self.communication = ProcessCommunication(
            self.name,
            self.queues,
            self.router_manager,
            self.shared_resources,
            logger_callback=self._fallback_log,
        )

        # Регистрация очередей
        self.communication.register_process_queues()
        self.communication.register_router_channels()

    def _init_state_proxy(self) -> None:
        """Авто-регистрация handler'а state.changed (ADR-SS-006).

        Вызывается в конце initialize(). Если state_proxy задан и router_manager
        доступен — регистрирует on_state_changed как обработчик IPC-сообщений.
        """
        if self.state_proxy is None or self.router_manager is None:
            return
        try:
            self.router_manager.register_message_handler("state.changed", self.state_proxy.on_state_changed)
            self._log_debug(
                f"ProcessModule '{self.name}': state_proxy handler state.changed зарегистрирован",
                module="state",
            )
        except Exception as exc:
            self._log_warning(
                f"ProcessModule '{self.name}': не удалось зарегистрировать state_proxy handler: {exc}",
                module="state",
            )

    def _register_process_state(self):
        """Регистрация состояния процесса."""
        self._state.register()

    def update_process_state(
        self,
        status: str | None = None,
        events: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        custom: dict[str, Any] | None = None,
    ):
        """
        Обновление состояния процесса.

        Args:
            status: Новый статус процесса (ready, running, stopping, error)
            events: События для добавления
            metadata: Метаданные для обновления
            custom: Кастомные данные для обновления
        """
        self._state.update(status=status, events=events, metadata=metadata, custom=custom)

    # ========================================================================
    # СИСТЕМНЫЕ ПОТОКИ
    # ========================================================================

    def _init_system_threads(self):
        """Инициализация системных потоков."""
        self._threads.initialize()

    def _stop_system_threads(self):
        """Остановка системных потоков."""
        self._threads.stop()

    # ========================================================================
    # ХУКИ ДЛЯ ДОЧЕРНИХ КЛАССОВ
    # ========================================================================

    def _init_custom_managers(self):
        """Опциональная инициализация кастомных менеджеров.

        Если config["plugins"] задан — создаёт PluginOrchestrator
        и загружает плагины (early-init: configure_managers).
        Дочерние классы могут переопределить для дополнительной логики.
        """
        app_cfg = self.get_config("config") or {}
        plugin_defs: list[dict] = app_cfg.get("plugins", [])

        if plugin_defs:
            from ..generic.plugin_orchestrator import PluginOrchestrator
            from ..io import ProcessIO

            io = ProcessIO(self)
            self._orchestrator = PluginOrchestrator(services=self, io=io)
            self._orchestrator.load_and_configure_managers(plugin_defs)

    def _init_application_threads(self):
        """Опциональная инициализация потоков приложения."""
        # Создание воркеров из config["workers"] (конфиг-драйвен)
        workers_config = self.config.get("workers") if self.config else {}
        if workers_config and self.worker_manager:
            self._create_workers_from_config(workers_config)

        # Plugin boot (если orchestrator создан в _init_custom_managers)
        if self._orchestrator is not None:
            self._orchestrator.boot()

    def _create_workers_from_config(self, workers_config: dict[str, Any]) -> None:
        """Создать воркеры из config. worker_dict: {class: path, config: {...}, thread: {...}}."""
        from ...worker_module import ThreadConfig

        for name, wc in workers_config.items():
            if not isinstance(wc, dict) or "class" not in wc:
                continue
            try:
                module_path, class_name = wc["class"].rsplit(".", 1)
                module = importlib.import_module(module_path)
                cls = getattr(module, class_name)
                instance = cls(process=self, config=wc.get("config", {}))
                target = getattr(instance, "run", instance)
                if not callable(target):
                    raise TypeError(f"Worker '{name}' must have run(stop_event, pause_event) or be callable")
                thread_dict = wc.get("thread", {})
                thread_config = ThreadConfig.from_dict(thread_dict)
                self.worker_manager.create_worker(name, target, thread_config)
            except Exception as e:
                self._log_error(f"Failed to create worker '{name}': {e}")

    # ========================================================================
    # ФЛАГ ОСТАНОВКИ
    # ========================================================================

    def should_stop(self) -> bool:
        """Проверка флага остановки."""
        return self._stop_requested

    # ========================================================================
    # УДОБНЫЕ СВОЙСТВА ДЛЯ ДОСТУПА К КОМПОНЕНТАМ
    # ========================================================================

    @property
    def managers(self):
        """Доступ к менеджерам через ObservableMixin."""
        return {
            "logger": self.logger_manager,
            "command": self.command_manager,
            "router": self.router_manager,
            "worker": self.worker_manager,
            "console": self.console_manager,
        }

    @property
    def adapters(self):
        """
        Доступ к адаптерам (словарь {manager_name: adapter}).

        Note: Рекомендуется использовать доступ через менеджеры:
        process.command_manager.get_adapter() или process.command_adapter
        """
        adapters = {}
        for manager_name, manager in self.managers.items():
            if manager and hasattr(manager, "get_adapter"):
                adapter = manager.get_adapter()
                if adapter:
                    adapters[manager_name] = adapter
        return adapters

    @property
    def router(self):
        """Прямой доступ к роутеру для отправки сообщений."""
        return self.router_manager

    @property
    def logger_adapter(self):
        """Доступ к logger_adapter через менеджера."""
        return self.logger_manager.get_adapter() if self.logger_manager else None

    @property
    def command_adapter(self):
        """Доступ к command_adapter через менеджера."""
        return self.command_manager.get_adapter() if self.command_manager else None

    @property
    def router_adapter(self):
        """Доступ к router_adapter через менеджера."""
        return self.router_manager.get_adapter() if self.router_manager else None

    @property
    def worker_adapter(self):
        """Доступ к worker_adapter через менеджера."""
        return self.worker_manager.get_adapter() if self.worker_manager else None

    @property
    def console_adapter(self):
        """Доступ к console_adapter через менеджера."""
        return self.console_manager.get_adapter() if self.console_manager else None

    # ========================================================================
    # ЛОГИРОВАНИЕ (модуль = имя процесса для маршрутизации в отдельные файлы)
    # ========================================================================

    def _log(self, level: str, message: str, **kwargs) -> None:
        kwargs.setdefault("module", self.name)
        super()._log(level, message, **kwargs)

    def _log_debug(self, message: str, **kwargs) -> None:
        kwargs.setdefault("module", self.name)
        super()._log_debug(message, **kwargs)

    def _log_info(self, message: str, **kwargs) -> None:
        kwargs.setdefault("module", self.name)
        super()._log_info(message, **kwargs)

    def _log_warning(self, message: str, **kwargs) -> None:
        kwargs.setdefault("module", self.name)
        super()._log_warning(message, **kwargs)

    def _log_error(self, message: str, **kwargs) -> None:
        kwargs.setdefault("module", self.name)
        super()._log_error(message, **kwargs)

    def _log_critical(self, message: str, **kwargs) -> None:
        kwargs.setdefault("module", self.name)
        super()._log_critical(message, **kwargs)

    # ========================================================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ========================================================================

    def _fallback_log(self, level: str, msg: str, ctx: str = None):
        """Fallback логирование через ObservableMixin."""
        log_fn = getattr(self, f"_log_{level.lower()}", self._log_info)
        log_fn(f"{ctx or self.name}: {msg}")

    def get_config(self, key: str, default: Any = None) -> Any:
        """Получить значение конфигурации."""
        return self.config_handler.get(key, default) if self.config_handler else self.config.get(key, default)

    def update_config(self, key: str, value: Any):
        """Обновить значение конфигурации."""
        if self.config_handler:
            self.config_handler.update(key, value)
        self.config[key] = value

    # ========================================================================
    # КОММУНИКАЦИЯ (делегирование к ProcessCommunication)
    # ========================================================================

    def send_message(self, target: str, message):
        """Отправить сообщение другому процессу."""
        if self.communication:
            return self.communication.send_message(target, message)
        return False

    def broadcast_message(self, message, exclude_self: bool = True):
        """Отправить broadcast сообщение."""
        if self.communication:
            return self.communication.broadcast_message(message, exclude_self)
        return False

    def receive_message(self, timeout: float = None, channel_types=None):
        """Получить сообщение из очереди.
        channel_types=['data'] — для воркеров, получающих DATA/EVENT (по умолчанию).
        channel_types=['system'] — для воркеров, получающих COMMAND (например Robot).
        """
        if self.communication:
            return self.communication.receive_message(timeout, channel_types)
        return None

    # ========================================================================
    # МЕТОДЫ ДЕЛЕГИРОВАНИЯ (для совместимости со старым API)
    # ========================================================================

    def register_manager(self, name: str, manager, enabled: bool = True):
        """Регистрация менеджера (делегирование к ObservableMixin напрямую)."""
        # Вызываем напрямую ObservableMixin, чтобы избежать рекурсии через ProcessManagers
        ObservableMixin.register_manager(self, name, manager, enabled=enabled)

    def get_manager(self, name: str):
        """Получение менеджера по имени (делегирование к ObservableMixin напрямую)."""
        # Вызываем напрямую ObservableMixin, чтобы избежать рекурсии через ProcessManagers
        return ObservableMixin.get_manager(self, name)

    # ========================================================================
    # КОММУНИКАЦИЯ (расширенные методы для совместимости)
    # ========================================================================

    def send(self, message) -> dict:
        """
        Универсальная отправка сообщения.

        Args:
            message: BaseMessage или Dict

        Returns:
            Dict: Результат отправки
        """
        if self.communication:
            return self.communication.send(message)
        return {"status": "error", "reason": "Communication not initialized"}

    def receive(self, timeout: float = 0.01, channel_types=None) -> list:
        """
        Получение входящих сообщений из каналов.

        Args:
            timeout: Таймаут опроса
            channel_types: Фильтр каналов (['data'] или ['system']). None — все каналы.

        Returns:
            List[Dict]: Список полученных сообщений
        """
        if self.communication:
            return self.communication.receive(timeout, channel_types)
        return []

    def send_to_process(self, target: str, message: dict) -> bool:
        """Отправка сообщения конкретному процессу."""
        if self.communication:
            return self.communication.send_to_process(target, message)
        return False

    # ========================================================================
    # УДОБНЫЕ МЕТОДЫ
    # ========================================================================

    def execute_command(self, command: str, data: dict = None) -> Any:
        """
        Выполнение команды через адаптер.

        Args:
            command: Имя команды
            data: Данные команды

        Returns:
            Результат выполнения команды
        """
        adapter = self.command_adapter
        if adapter and hasattr(adapter, "execute"):
            return adapter.execute(command, data)
        return None

    # ========================================================================
    # ЖИЗНЕННЫЙ ЦИКЛ (расширенные методы)
    # ========================================================================

    def run(self):
        """Запуск процесса — статус RUNNING, старт воркеров, heartbeat."""
        self.update_process_state(status=ProcessStatus.RUNNING.value)

        if self.worker_manager:
            self.worker_manager.start_all_workers()

        # Встроенные команды (composition)
        from ..commands.builtin_commands import BuiltinCommands

        self._builtin_cmds = BuiltinCommands(self)
        self._builtin_cmds.register()
        # P4.4.1 (B2): builtins (worker.*/wire.*/introspect.*) живут в CommandManager;
        # ре-синк в message_dispatcher больше не нужен — kind-router в receive()
        # диспатчит type=="command" напрямую в CommandManager.

        # Heartbeat (composition)
        from ..heartbeat.process_heartbeat import ProcessHeartbeat

        self._heartbeat = ProcessHeartbeat(self)
        self._heartbeat.start()

        self._log_info(f"Process '{self.name}' started", module="lifecycle")

    def stop(self):
        """Остановка процесса — статус STOPPING, остановка воркеров и shutdown."""
        self.update_process_state(status=ProcessStatus.STOPPING.value)

        self._log_info(f"Process '{self.name}' stopping", module="lifecycle")
        self._stop_requested = True

        if self.worker_manager:
            self.worker_manager.stop_all_workers()

        self.shutdown()

    # ========================================================================
    # СТАТИСТИКА
    # ========================================================================

    def get_stats(self) -> dict[str, Any]:
        """
        Получение статистики процесса.

        Returns:
            Dict: Статистика всех компонентов
        """
        # Базовая статистика из BaseManager
        stats = super().get_stats()

        # Добавляем специфичную статистику процесса
        stats.update(
            {
                "name": self.name,
                "running": not self._stop_requested,
            }
        )

        # Статистика очередей
        if self.communication and hasattr(self.communication, "get_queue_stats"):
            stats["queues"] = self.communication.get_queue_stats()

        # Статистика воркеров
        if self.worker_manager and hasattr(self.worker_manager, "get_stats"):
            try:
                stats["workers"] = self.worker_manager.get_stats()
            except Exception as e:
                stats["workers"] = {"error": str(e)}

        return stats
