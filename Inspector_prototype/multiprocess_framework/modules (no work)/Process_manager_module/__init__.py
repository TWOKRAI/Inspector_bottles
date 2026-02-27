"""
Process Manager Module - Модуль управления процессами.

Библиотека для создания многопроцессных приложений с централизованным управлением.

Модуль организован по папкам с четкой ответственностью:
- core/ - утилитарные классы (ProcessManagerCore, ProcessLifecycle, ProcessPriority, ProcessStatus)
- process/ - ProcessManager (главный процесс системы)
- bootstrap/ - ProcessManagerBootstrap (запуск ProcessManager)
- launcher/ - SystemLauncher (высокоуровневый интерфейс для запуска системы)
- legacy/ - ProcessManager (старая версия для обратной совместимости)
- config/ - конфигурация процессов (ProcessConfig)
- runner/ - запуск процессов (_run_process_function)
- platforms/ - платформо-зависимые адаптеры (Windows, Linux)

ProcessManager выступает как:
- Централизованное хранилище SharedResources
- Мониторинг всех процессов в системе
- Широковещательное общение между процессами
- Управление процессами в реальном времени (создание, запуск, остановка)
- Точка связывания всех процессов
"""

# Новая архитектура
from .bootstrap import ProcessManagerBootstrap
from .process import ProcessManager
from .core import ProcessManagerCore

# Core компоненты
from .core import ProcessLifecycle, ProcessPriority, ProcessStatus
from .config import ProcessConfig
from .runner import _run_process_function

# Launcher (высокоуровневый интерфейс)
from .launcher import SystemLauncher, main as launcher_main

# Legacy (для обратной совместимости)
from .legacy import ProcessManager as LegacyProcessManager

# Платформы
from .platforms import get_platform_adapter

# Builders (декларативный подход)
from .builders import (
    process,
    worker,
    queue,
    ProcessConfig,
    WorkerConfig,
    QueueConfig,
    ConsoleConfig,
    ProcessRegistry,
    export_process_data_to_config,
    export_all_processes_to_config,
    save_config_to_yaml,
    load_config_from_yaml,
    export_process_to_yaml,
    export_all_processes_to_yaml,
)

__all__ = [
    # Новая архитектура
    'ProcessManagerBootstrap',
    'ProcessManager',
    'ProcessManagerCore',
    # Core компоненты
    'ProcessLifecycle',
    'ProcessPriority',
    'ProcessStatus',
    'ProcessConfig',
    '_run_process_function',
    # Launcher (высокоуровневый интерфейс)
    'SystemLauncher',
    'launcher_main',
    # Legacy (обратная совместимость)
    'LegacyProcessManager',
    # Платформы
    'get_platform_adapter',
    # Builders (декларативный подход)
    'process',
    'worker',
    'queue',
    'ProcessConfig',
    'WorkerConfig',
    'QueueConfig',
    'ConsoleConfig',
    'ProcessRegistry',
    'export_process_data_to_config',
    'export_all_processes_to_config',
    'save_config_to_yaml',
    'load_config_from_yaml',
    'export_process_to_yaml',
    'export_all_processes_to_yaml',
]

