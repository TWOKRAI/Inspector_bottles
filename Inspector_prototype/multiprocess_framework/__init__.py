"""
Multiprocess Framework — многопроцессный фреймворк (v2).

Рефакторинг: чёткое разделение ответственности, Router как транспорт сообщений,
Dict at Boundary для IPC. Публичный код модулей: ``multiprocess_framework.modules``.

Экспорты с корня пакета сгруппированы по уровням (см. ``__all__``). Тяжёлые цепочки
импорта обёрнуты в ``try``/``except`` — при ошибке символ остаётся ``None``.

Пример::

    from multiprocess_framework import SystemLauncher, ProcessModule, SchemaBase, process
"""

__version__ = "2.0.0"

# === TIER 1: ESSENTIAL ===
try:
    from .modules.process_manager_module import SystemLauncher
except (ImportError, ModuleNotFoundError):
    SystemLauncher = None  # type: ignore[misc, assignment]

try:
    from .modules.data_schema_module import process, SchemaBase, FieldMeta, FieldRouting
except (ImportError, ModuleNotFoundError):
    process = SchemaBase = FieldMeta = FieldRouting = None  # type: ignore[misc, assignment]

try:
    from .modules.process_module import ProcessModule
except (ImportError, ModuleNotFoundError):
    ProcessModule = None  # type: ignore[misc, assignment]

try:
    from .modules.message_module import Message
except (ImportError, ModuleNotFoundError):
    Message = None  # type: ignore[misc, assignment]

# === TIER 2: PROCESS ===
try:
    from .modules.shared_resources_module import (
        ProcessData,
        ProcessDataKeys,
        QueueRegistry,
        SharedResourcesManager,
    )
except (ImportError, ModuleNotFoundError):
    ProcessData = ProcessDataKeys = QueueRegistry = SharedResourcesManager = None  # type: ignore[misc, assignment]

try:
    from .modules.config_module import ConfigManager
except (ImportError, ModuleNotFoundError):
    ConfigManager = None  # type: ignore[misc, assignment]

try:
    from .modules.worker_module import ThreadConfig, ThreadPriority, WorkerManager, WorkerStatus
except (ImportError, ModuleNotFoundError):
    ThreadConfig = ThreadPriority = WorkerManager = WorkerStatus = None  # type: ignore[misc, assignment]

# === TIER 3: COMMUNICATION ===
try:
    from .modules.message_module import MessageAdapter, MessageType
except (ImportError, ModuleNotFoundError):
    MessageAdapter = MessageType = None  # type: ignore[misc, assignment]

try:
    from .modules.router_module import RouterManager
except (ImportError, ModuleNotFoundError):
    RouterManager = None  # type: ignore[misc, assignment]

try:
    from .modules.command_module import CommandManager
except (ImportError, ModuleNotFoundError):
    CommandManager = None  # type: ignore[misc, assignment]

try:
    from .modules.dispatch_module import (
        DispatchStrategy,
        Dispatcher,
        HandlerInfo,
        Scenario,
        ScenarioBuilder,
    )
except (ImportError, ModuleNotFoundError):
    DispatchStrategy = Dispatcher = HandlerInfo = Scenario = ScenarioBuilder = None  # type: ignore[misc, assignment]

# === TIER 4: OBSERVABILITY ===
try:
    from .modules.logger_module import LoggerManager, LoggerManagerConfig, get_logger
except (ImportError, ModuleNotFoundError):
    LoggerManagerConfig = LoggerManager = get_logger = None  # type: ignore[misc, assignment]

try:
    from .modules.error_module import ErrorManager
except (ImportError, ModuleNotFoundError):
    ErrorManager = None  # type: ignore[misc, assignment]

try:
    from .modules.statistics_module import StatsManager
except (ImportError, ModuleNotFoundError):
    StatsManager = None  # type: ignore[misc, assignment]

# === TIER 5: ADVANCED / ORCHESTRATION INTERNALS ===
try:
    from .modules.base_manager import BaseAdapter, BaseManager, ObservableMixin
except (ImportError, ModuleNotFoundError):
    BaseAdapter = BaseManager = ObservableMixin = None  # type: ignore[misc, assignment]

try:
    from .modules.channel_routing_module import ChannelRoutingManager
except (ImportError, ModuleNotFoundError):
    ChannelRoutingManager = None  # type: ignore[misc, assignment]

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
    )
except (ImportError, ModuleNotFoundError):
    ISystemLauncher = IProcessManagerProcess = IProcessRegistry = None  # type: ignore[misc, assignment]
    ProcessManagerProcess = ProcessMonitor = ProcessPriority = None  # type: ignore[misc, assignment]
    ProcessRegistry = ProcessSchemaAdapter = ProcessSpawner = ProcessStatus = None  # type: ignore[misc, assignment]

try:
    from .modules.shared_resources_module import EventManager, EventType
except (ImportError, ModuleNotFoundError):
    EventManager = EventType = None  # type: ignore[misc, assignment]

try:
    from .modules.console_module import ConsoleManager
except (ImportError, ModuleNotFoundError):
    ConsoleManager = None  # type: ignore[misc, assignment]

__all__ = [
    "__version__",
    # Tier 1
    "SystemLauncher",
    "process",
    "SchemaBase",
    "FieldMeta",
    "FieldRouting",
    "ProcessModule",
    "Message",
    # Tier 2
    "SharedResourcesManager",
    "ProcessData",
    "ProcessDataKeys",
    "QueueRegistry",
    "ConfigManager",
    "WorkerManager",
    "ThreadConfig",
    "ThreadPriority",
    "WorkerStatus",
    # Tier 3
    "MessageType",
    "MessageAdapter",
    "RouterManager",
    "CommandManager",
    "Dispatcher",
    "DispatchStrategy",
    "HandlerInfo",
    "Scenario",
    "ScenarioBuilder",
    # Tier 4
    "LoggerManager",
    "LoggerManagerConfig",
    "get_logger",
    "ErrorManager",
    "StatsManager",
    # Tier 5
    "BaseManager",
    "ObservableMixin",
    "BaseAdapter",
    "ChannelRoutingManager",
    "ISystemLauncher",
    "IProcessManagerProcess",
    "IProcessRegistry",
    "ProcessSpawner",
    "ProcessManagerProcess",
    "ProcessRegistry",
    "ProcessPriority",
    "ProcessStatus",
    "ProcessMonitor",
    "ProcessSchemaAdapter",
    "EventManager",
    "EventType",
    "ConsoleManager",
]
