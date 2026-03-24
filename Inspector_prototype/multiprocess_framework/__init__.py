"""
Multiprocess Framework — многопроцессный фреймворк (v2).

Рефакторинг: чёткое разделение ответственности, Router как транспорт сообщений,
Dict at Boundary для IPC. Публичный код модулей: ``multiprocess_framework.modules``.

Основные направления:
- process_manager_module — SystemLauncher, ProcessManagerProcess, реестр процессов
- process_module, message_module, router_module, worker_module
- data_schema_module — SchemaBase, ``process()`` для сборки конфигов процессов

Пример импорта (рекомендуется явный путь к модулю):

    from multiprocess_framework.modules.process_manager_module import SystemLauncher
    from multiprocess_framework.modules.data_schema_module import process
"""

__version__ = "2.0.0"

# Реэкспорты с корня пакета (опционально; тяжёлые цепочки импорта — через try)
try:
    from .modules.process_manager_module import (
        ISystemLauncher,
        IProcessManagerProcess,
        IProcessRegistry,
        ProcessManagerProcess,
        ProcessMonitor,
        ProcessPriority,
        ProcessRegistry,
        ProcessSchemaAdapter,
        ProcessSpawner,
        ProcessStatus,
        SystemLauncher,
    )
except (ImportError, ModuleNotFoundError):
    ISystemLauncher = IProcessManagerProcess = IProcessRegistry = None
    ProcessManagerProcess = ProcessMonitor = ProcessPriority = None
    ProcessRegistry = ProcessSchemaAdapter = ProcessSpawner = ProcessStatus = None
    SystemLauncher = None

try:
    from .modules.data_schema_module import process
except (ImportError, ModuleNotFoundError):
    process = None

try:
    from .modules.process_module import ProcessModule
except (ImportError, ModuleNotFoundError):
    ProcessModule = None

try:
    from .modules.shared_resources_module import (
        EventManager,
        EventType,
        ProcessData,
        ProcessDataKeys,
        QueueRegistry,
        SharedResourcesManager,
    )
except (ImportError, ModuleNotFoundError):
    EventManager = EventType = ProcessData = ProcessDataKeys = None
    QueueRegistry = SharedResourcesManager = None

try:
    from .modules.message_module import Message, MessageAdapter, MessageType
except (ImportError, ModuleNotFoundError):
    Message = MessageAdapter = MessageType = None

try:
    from .modules.router_module import RouterManager
except (ImportError, ModuleNotFoundError):
    RouterManager = None

try:
    from .modules.logger_module import LogConfig, LoggerManager, get_logger
except (ImportError, ModuleNotFoundError):
    LogConfig = LoggerManager = get_logger = None

try:
    from .modules.config_module import ConfigManager
except (ImportError, ModuleNotFoundError):
    ConfigManager = None

try:
    from .modules.console_module import ConsoleManager
except (ImportError, ModuleNotFoundError):
    ConsoleManager = None

try:
    from .modules.command_module import CommandManager
except (ImportError, ModuleNotFoundError):
    CommandManager = None

try:
    from .modules.worker_module import (
        ThreadConfig,
        ThreadPriority,
        WorkerManager,
        WorkerStatus,
    )
except (ImportError, ModuleNotFoundError):
    ThreadConfig = ThreadPriority = WorkerManager = WorkerStatus = None

try:
    from .modules.dispatch_module import (
        DispatchStrategy,
        Dispatcher,
        HandlerInfo,
        Scenario,
        ScenarioBuilder,
    )
except (ImportError, ModuleNotFoundError):
    DispatchStrategy = Dispatcher = HandlerInfo = Scenario = ScenarioBuilder = None

__all__ = [
    "__version__",
    "ISystemLauncher",
    "IProcessManagerProcess",
    "IProcessRegistry",
    "SystemLauncher",
    "ProcessSpawner",
    "ProcessManagerProcess",
    "ProcessRegistry",
    "ProcessPriority",
    "ProcessStatus",
    "ProcessMonitor",
    "ProcessSchemaAdapter",
    "process",
    "ProcessModule",
    "SharedResourcesManager",
    "ProcessData",
    "ProcessDataKeys",
    "QueueRegistry",
    "EventManager",
    "EventType",
    "Message",
    "MessageType",
    "MessageAdapter",
    "RouterManager",
    "LoggerManager",
    "LogConfig",
    "get_logger",
    "ConfigManager",
    "ConsoleManager",
    "CommandManager",
    "WorkerManager",
    "ThreadConfig",
    "ThreadPriority",
    "WorkerStatus",
    "Dispatcher",
    "DispatchStrategy",
    "HandlerInfo",
    "Scenario",
    "ScenarioBuilder",
]
