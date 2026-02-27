"""
Builders - декларативный подход для создания процессов.

Предоставляет удобные инструменты для декларативного определения процессов:
- Декораторы (@process, @worker, @queue)
- Классы-конфигурации (ProcessConfig, WorkerConfig, QueueConfig)
- ProcessRegistry для автоматической регистрации
- Утилиты экспорта конфигов из ProcessData

Пример использования:
    # Декораторы
    from ...Process_manager_module.builders import process, worker, queue
    
    @process(name="ChatProcess", priority="normal")
    class ChatProcess(ProcessModule):
        @worker(name="message_handler", priority="normal")
        def handle_messages(self):
            pass
    
    # Классы-конфигурации
    from ...Process_manager_module.builders import ProcessConfig, QueueConfig
    
    config = ProcessConfig(
        name="ChatProcess",
        class_path="module.ChatProcess",
        queues={"messages": QueueConfig(maxsize=100)}
    )
    
    # Регистрация
    from ...Process_manager_module.builders import ProcessRegistry
    
    registry = ProcessRegistry()
    registry.register_decorated(ChatProcess)
    registry.apply_to(pm)
"""

from .decorators import (
    process,
    worker,
    queue,
    get_decorated_processes,
    get_process_metadata,
    get_worker_metadata,
    get_queue_metadata
)

from .configs import (
    ProcessConfig,
    WorkerConfig,
    QueueConfig,
    ConsoleConfig
)

from .registry import ProcessRegistry

from .export import (
    export_process_data_to_config,
    export_all_processes_to_config,
    save_config_to_yaml,
    load_config_from_yaml,
    export_process_to_yaml,
    export_all_processes_to_yaml
)

__all__ = [
    # Декораторы
    'process',
    'worker',
    'queue',
    'get_decorated_processes',
    'get_process_metadata',
    'get_worker_metadata',
    'get_queue_metadata',
    # Классы-конфигурации
    'ProcessConfig',
    'WorkerConfig',
    'QueueConfig',
    'ConsoleConfig',
    # Реестр
    'ProcessRegistry',
    # Экспорт
    'export_process_data_to_config',
    'export_all_processes_to_config',
    'save_config_to_yaml',
    'load_config_from_yaml',
    'export_process_to_yaml',
    'export_all_processes_to_yaml',
]
