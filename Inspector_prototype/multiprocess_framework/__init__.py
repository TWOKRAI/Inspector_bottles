"""
Multiprocess Framework - Многопроцессный фреймворк для создания распределенных приложений.

Основные компоненты:
- ProcessManager: Управление процессами и их жизненным циклом
- ProcessModule: Базовый класс для всех процессов
- SharedResources: Управление общими ресурсами между процессами
- Message: Система сообщений между процессами
- Router: Маршрутизация сообщений
- Logger: Система логирования
- Config: Управление конфигурацией
- Console: Консольный интерфейс
- Command: Система команд
- Worker: Управление потоками
- Dispatch: Диспетчеризация событий
- GUI: GUI компоненты

Использование:
    from multiprocess_framework import SystemLauncher, ProcessConfig
    from multiprocess_framework import ProcessModule, process, worker
    from multiprocess_framework import SharedResourcesManager, ProcessDataKeys
"""

# Версия пакета
__version__ = "1.0.0"

# Импорт основных компонентов для удобного доступа
# Опциональные импорты: если модули не доступны (например, в тестовом окружении), пропускаем
try:
    from .modules.Process_manager_module import (
        SystemLauncher,
        ProcessManager,
        ProcessManagerCore,
        ProcessConfig,
        ProcessLifecycle,
        ProcessPriority,
        ProcessStatus,
        process,
        worker,
        ProcessRegistry,
    )
except (ImportError, ModuleNotFoundError):
    # Модули не доступны (например, в тестовом окружении или при рефакторинге)
    SystemLauncher = None
    ProcessManager = None
    ProcessManagerCore = None
    ProcessConfig = None
    ProcessLifecycle = None
    ProcessPriority = None
    ProcessStatus = None
    process = None
    worker = None
    ProcessRegistry = None

try:
    from .modules.Process_module import ProcessModule
except (ImportError, ModuleNotFoundError):
    ProcessModule = None

try:
    from .modules.Shared_resources_module import (
        SharedResourcesManager,
        ProcessData,
        ProcessDataKeys,
        QueueRegistry,
        EventManager,
        EventType,
    )
except (ImportError, ModuleNotFoundError):
    SharedResourcesManager = None
    ProcessData = None
    ProcessDataKeys = None
    QueueRegistry = None
    EventManager = None
    EventType = None

try:
    from .modules.Message_module import Message, MessageType
except (ImportError, ModuleNotFoundError):
    Message = None
    MessageType = None

try:
    from .modules.Router_module import RouterManager
except (ImportError, ModuleNotFoundError):
    RouterManager = None

try:
    from .modules.Logger_module import LoggerManager, LogConfig, get_logger
except (ImportError, ModuleNotFoundError):
    LoggerManager = None
    LogConfig = None
    get_logger = None

try:
    from .modules.Config_module import ConfigManager
except (ImportError, ModuleNotFoundError):
    ConfigManager = None

try:
    from .modules.Console_module import ConsoleManager
except (ImportError, ModuleNotFoundError):
    ConsoleManager = None

try:
    from .modules.Command_module import CommandManager
except (ImportError, ModuleNotFoundError):
    CommandManager = None

try:
    from .modules.Worker_module import WorkerManager, ThreadConfig, ThreadPriority, WorkerStatus
except (ImportError, ModuleNotFoundError):
    WorkerManager = None
    ThreadConfig = None
    ThreadPriority = None
    WorkerStatus = None

try:
    from .modules.Dispatch_module import Dispatcher, DispatchStrategy, HandlerInfo, Scenario
except (ImportError, ModuleNotFoundError):
    Dispatcher = None
    DispatchStrategy = None
    HandlerInfo = None
    Scenario = None

try:
    from .modules.GUI_module import GUIProcessModule, BaseWindowManager, WindowConfig
except (ImportError, ModuleNotFoundError):
    GUIProcessModule = None
    BaseWindowManager = None
    WindowConfig = None

__all__ = [
    # Версия
    "__version__",
    # Process Manager
    "SystemLauncher",
    "ProcessManager",
    "ProcessManagerCore",
    "ProcessConfig",
    "ProcessLifecycle",
    "ProcessPriority",
    "ProcessStatus",
    "process",
    "worker",
    "ProcessRegistry",
    # Process Module
    "ProcessModule",
    # Shared Resources
    "SharedResourcesManager",
    "ProcessData",
    "ProcessDataKeys",
    "QueueRegistry",
    "EventManager",
    "EventType",
    # Message
    "Message",
    "MessageType",
    # Router
    "RouterManager",
    # Logger
    "LoggerManager",
    "LogConfig",
    "get_logger",
    # Config
    "ConfigManager",
    # Console
    "ConsoleManager",
    # Command
    "CommandManager",
    # Worker
    "WorkerManager",
    "ThreadConfig",
    "ThreadPriority",
    "WorkerStatus",
    # Dispatch
    "Dispatcher",
    "DispatchStrategy",
    "HandlerInfo",
    "Scenario",
    # GUI
    "GUIProcessModule",
    "BaseWindowManager",
    "WindowConfig",
]

