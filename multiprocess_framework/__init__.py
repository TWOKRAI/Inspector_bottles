"""Multiprocess Framework — конструктор многопроцессных приложений на Python (v2).

Скрывает многопроцессорную «боль» Python (spawn/fork, pickle-safe сериализацию,
жизненный цикл процессов, IPC, маршрутизацию, наблюдаемость) и даёт разработчику
готовые «детали»-модули, которые собираются друг в друга через явные интерфейсы.

Ключ всей идеи — **регистр-ориентированная модель**: ``SchemaBase``-наследник
с ``FieldMeta`` + ``FieldRouting`` на каждом поле даёт одновременно тип, валидацию,
UI-метаданные, дефолт и маршрут между процессами. Регистр — единый источник истины
для бэкенда и фронтенда; ``RouterManager`` по ``FieldRouting`` знает, в какой процесс
и канал отправить изменение.

Корневой фасад экспортирует **полный публичный API** фреймворка. Импорты сгруппированы
по слоям (см. ``__all__``).

Пример::

    from multiprocess_framework import SystemLauncher, ProcessModule, SchemaBase, process
"""

from __future__ import annotations

__version__ = "2.0.0"

# === LAYER 1: FOUNDATION ===
from multiprocess_framework.modules.base_manager import (
    BaseAdapter,
    BaseManager,
    ObservableMixin,
)
from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    FieldRouting,
    SchemaBase,
    process,
)
from multiprocess_framework.modules.message_module import (
    Message,
    MessageAdapter,
    MessageType,
)

# === LAYER 2: ROUTING PRIMITIVES ===
from multiprocess_framework.modules.channel_routing_module import ChannelRoutingManager
from multiprocess_framework.modules.dispatch_module import (
    DispatchStrategy,
    Dispatcher,
    HandlerInfo,
    Scenario,
    ScenarioBuilder,
)

# === LAYER 3: MESSAGING ===
from multiprocess_framework.modules.router_module import RouterManager

# === LAYER 4: OBSERVABILITY ===
from multiprocess_framework.modules.error_module import ErrorManager
from multiprocess_framework.modules.logger_module import (
    LoggerManager,
    LoggerManagerConfig,
    get_logger,
)
from multiprocess_framework.modules.statistics_module import StatsManager

# === LAYER 5: RESOURCES & CONFIG ===
from multiprocess_framework.modules.config_module import ConfigManager
from multiprocess_framework.modules.shared_resources_module import (
    EventManager,
    EventType,
    ProcessData,
    ProcessDataKeys,
    QueueRegistry,
    SharedResourcesManager,
)

# === LAYER 6: COMMAND & WORK ===
from multiprocess_framework.modules.command_module import CommandManager
from multiprocess_framework.modules.worker_module import (
    ThreadConfig,
    ThreadPriority,
    WorkerManager,
    WorkerStatus,
)

# === LAYER 7: PROCESS ===
from multiprocess_framework.modules.console_module import ConsoleManager
from multiprocess_framework.modules.process_module import ProcessModule

# === LAYER 8: ORCHESTRATION ===
from multiprocess_framework.modules.process_manager_module import (
    IProcessManagerProcess,
    IProcessRegistry,
    ISystemLauncher,
    ProcessManagerProcess,
    ProcessMonitor,
    ProcessPriority,
    ProcessRegistry,
    ProcessSchemaAdapter,
    ProcessSpawner,
    ProcessStatusMonitor,
    SystemLauncher,
)

# ProcessStatus enum — единый источник (ADR-117), уже импортирован из base_manager (LAYER 1)
from multiprocess_framework.modules.base_manager import ProcessStatus

# === LAYER 9: STORAGE ===
# SQLManager переехал в Services/sql (Phase 4.1) — импортируйте напрямую:
#   from Services.sql import SQLManager

# === LAYER 10: APPLICATION KIT ===
from multiprocess_framework.modules.registers_module import RegistersManager

# === LAYER 5+: STATE STORE (реактивное дерево состояния) ===
from multiprocess_framework.modules.state_store_module import (
    GuiStateProxy,
    StateProxy,
    StateStoreManager,
)
from multiprocess_framework.modules.state_store_module import (
    IRouter as IStateRouter,
)

# === LAYER 6+: CHAIN ENGINE (DAG/Chain исполнители) ===
from multiprocess_framework.modules.chain_module import (
    ChainContext,
    ChainResult,
    ChainRunnable,
    DagRunnable,
    ParallelChainRunnable,
)

# === LAYER 11: UI (опционально — PySide6 может отсутствовать в headless-окружении) ===
try:
    from multiprocess_framework.modules.frontend_module import FrontendManager
except ImportError:
    FrontendManager = None  # type: ignore[assignment,misc]

__all__ = [
    "__version__",
    # Foundation
    "BaseAdapter",
    "BaseManager",
    "ObservableMixin",
    "FieldMeta",
    "FieldRouting",
    "SchemaBase",
    "process",
    "Message",
    "MessageAdapter",
    "MessageType",
    # Routing primitives
    "ChannelRoutingManager",
    "DispatchStrategy",
    "Dispatcher",
    "HandlerInfo",
    "Scenario",
    "ScenarioBuilder",
    # Messaging
    "RouterManager",
    # Observability
    "ErrorManager",
    "LoggerManager",
    "LoggerManagerConfig",
    "get_logger",
    "StatsManager",
    # Resources & config
    "ConfigManager",
    "EventManager",
    "EventType",
    "ProcessData",
    "ProcessDataKeys",
    "QueueRegistry",
    "SharedResourcesManager",
    # Command & work
    "CommandManager",
    "ThreadConfig",
    "ThreadPriority",
    "WorkerManager",
    "WorkerStatus",
    # Process
    "ConsoleManager",
    "ProcessModule",
    # Orchestration
    "IProcessManagerProcess",
    "IProcessRegistry",
    "ISystemLauncher",
    "ProcessManagerProcess",
    "ProcessMonitor",
    "ProcessPriority",
    "ProcessRegistry",
    "ProcessSchemaAdapter",
    "ProcessSpawner",
    "ProcessStatus",
    "ProcessStatusMonitor",
    "SystemLauncher",
    # Storage
    "SQLManager",
    # Application kit
    "RegistersManager",
    # State store
    "StateStoreManager",
    "StateProxy",
    "GuiStateProxy",
    "IStateRouter",
    # Chain engine
    "ChainRunnable",
    "DagRunnable",
    "ParallelChainRunnable",
    "ChainContext",
    "ChainResult",
    # UI (optional)
    "FrontendManager",
]
