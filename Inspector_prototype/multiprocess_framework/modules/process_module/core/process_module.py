"""
Базовый класс для всех процессов системы (Refactored).

Наследуется от BaseManager и использует ObservableMixin для логирования и мониторинга.
Все процессы теперь являются менеджерами с единым интерфейсом.
"""

import importlib
import time
from typing import Any

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
    ):
        """
        Инициализация процесса.

        Args:
            name: Имя процесса
            shared_resources: ISharedResources (DI — передаётся снаружи, не импортируется)
            config: Локальная конфигурация процесса (опционально)
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

        # Компоненты (настраиваются в initialize())
        self.config_handler = None
        self.communication = None
        self.queues = None
        self.queue_registry = None
        self.memory_manager = None

        self.stop_process = False

        # Менеджеры (создаются в initialize())
        self.worker_manager = None
        self.logger_manager = None
        self.command_manager = None
        self.router_manager = None
        self.console_manager = None

        # Внутренние компоненты (композиция)
        self._lifecycle = ProcessLifecycle(self)
        self._process_managers = ProcessManagers(self)
        self._threads = SystemThreads(self)
        self._state = ProcessState(self)

        # initialize() вызывается явно после создания

    # ========================================================================
    # РЕАЛИЗАЦИЯ BaseManager - ЖИЗНЕННЫЙ ЦИКЛ
    # ========================================================================

    def initialize(self) -> bool:
        """
        Инициализация процесса.

        Интегрирует функциональность ProcessCore:
        - Загрузка конфигурации из ProcessData
        - Создание очередей
        - Инициализация менеджеров через ObservableMixin
        - Настройка коммуникации

        Returns:
            bool: True если инициализация успешна
        """
        return self._lifecycle.initialize()

    def shutdown(self) -> bool:
        """
        Завершение работы процесса.

        Интегрирует функциональность ProcessCore:
        - Остановка всех потоков
        - Очистка ресурсов
        - Отключение менеджеров

        Returns:
            bool: True если завершение успешно
        """
        return self._lifecycle.shutdown()

    # ========================================================================
    # ИНИЦИАЛИЗАЦИЯ КОМПОНЕНТОВ
    # ========================================================================

    def _init_configuration(self) -> None:
        """Инициализация конфигурации процесса. Реализация в ProcessLifecycle."""
        self._lifecycle._init_configuration()

    def _init_queues(self) -> None:
        """Инициализация очередей процесса. Реализация в ProcessLifecycle."""
        self._lifecycle._init_queues()

    def _init_managers(self):
        """Инициализация менеджеров процесса через ObservableMixin."""
        self._process_managers.initialize()

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
        """Опциональная инициализация кастомных менеджеров."""
        # Переопределяется в дочерних классах
        pass

    def _init_application_threads(self):
        """Опциональная инициализация потоков приложения."""
        # Создание воркеров из config["workers"] (конфиг-драйвен)
        workers_config = self.config.get("workers") if self.config else {}
        if workers_config and self.worker_manager:
            self._create_workers_from_config(workers_config)
        # Дочерние классы могут переопределить для дополнительной логики
        pass

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
                    raise TypeError(
                        f"Worker '{name}' must have run(stop_event, pause_event) or be callable"
                    )
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
        return self.stop_process

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
        """Fallback логирование если ObservableMixin не доступен."""
        print(f"[{level}] {ctx or self.name}: {msg}")

    def get_config(self, key: str, default: Any = None) -> Any:
        """Получить значение конфигурации."""
        return (
            self.config_handler.get(key, default)
            if self.config_handler
            else self.config.get(key, default)
        )

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

    def log(self, level: str, message: str, context: str = None):
        """
        Логирование через адаптер (для совместимости со старым API).

        .. deprecated::
            Предпочтительно ``_log_info`` / ``_log_error`` и родственные методы
            или адаптер логгера; метод сохранён для подклассов и существующих тестов.

        Args:
            level: Уровень логирования (INFO, DEBUG, ERROR и т.д.)
            message: Текст сообщения
            context: Контекст логирования
        """
        # Используем ObservableMixin для логирования
        level_lower = level.lower()
        if level_lower == "info":
            self.log_info(message, module=context or self.name)
        elif level_lower == "debug":
            self.log_debug(message, module=context or self.name)
        elif level_lower == "error":
            self.log_error(message, module=context or self.name)
        elif level_lower == "warning":
            self.log_warning(message, module=context or self.name)
        else:
            # Fallback на адаптер если есть
            adapter = self.logger_adapter
            if adapter and hasattr(adapter, "log"):
                adapter.log(level, message, context or self.name)

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

        # Запуск heartbeat воркера (если интервал > 0)
        self._start_heartbeat_worker()

        self._log_info(f"Process '{self.name}' started", module="lifecycle")

    # ========================================================================
    # HEARTBEAT
    # ========================================================================

    def _start_heartbeat_worker(self) -> None:
        """Создать и запустить heartbeat воркер если включён в конфиге.

        Heartbeat отправляет периодическое сообщение ProcessManager-у,
        чтобы ProcessMonitor мог отличить зависший процесс от живого.
        Интервал задаётся через config['heartbeat_interval'] (default=5.0).
        Если heartbeat_interval <= 0 — heartbeat отключён.
        """
        heartbeat_interval = self.get_config("heartbeat_interval", 5.0)
        try:
            heartbeat_interval = float(heartbeat_interval)
        except (TypeError, ValueError):
            heartbeat_interval = 5.0

        if heartbeat_interval <= 0:
            self._log_debug("Heartbeat отключён (heartbeat_interval <= 0)", module="heartbeat")
            return

        if not self.worker_manager:
            return

        from ...worker_module import ThreadConfig, ThreadPriority

        self._heartbeat_interval = heartbeat_interval

        self.worker_manager.create_worker(
            "heartbeat_sender",
            self._heartbeat_loop,
            ThreadConfig(priority=ThreadPriority.LOW),
            auto_start=True,
        )
        self._log_debug(
            f"Heartbeat воркер запущен (interval={heartbeat_interval}с)",
            module="heartbeat",
        )

    def _heartbeat_loop(self, stop_event, pause_event) -> None:
        """Цикл отправки heartbeat-сообщений в ProcessManager."""
        interval = getattr(self, "_heartbeat_interval", 5.0)
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            try:
                heartbeat_msg = {
                    "type": "system",
                    "subtype": "heartbeat",
                    "command": "heartbeat",
                    "sender": self.name,
                    "timestamp": time.time(),
                }
                self.send_message("ProcessManager", heartbeat_msg)
            except Exception as exc:
                self._log_debug(f"Не удалось отправить heartbeat: {exc}", module="heartbeat")
            # Ожидание с проверкой stop_event для быстрого завершения
            stop_event.wait(timeout=interval)

    def stop(self):
        """Остановка процесса — статус STOPPING, остановка воркеров и shutdown."""
        self.update_process_state(status=ProcessStatus.STOPPING.value)

        self._log_info(f"Process '{self.name}' stopping", module="lifecycle")
        self.stop_process = True

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
                "running": not self.stop_process,
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
