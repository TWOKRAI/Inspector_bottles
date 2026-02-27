"""
Классы-конфигурации для декларативного создания процессов.

Предоставляют удобный программный способ создания конфигураций процессов,
воркеров и очередей через dataclass с валидацией.

Пример использования:
    from ...Process_manager_module.builders import ProcessConfig, QueueConfig, WorkerConfig
    
    config = ProcessConfig(
        name="MyProcess",
        class_path="module.MyProcess",
        priority="high",
        queues={
            "data": QueueConfig(maxsize=100),
            "results": QueueConfig(maxsize=50)
        },
        workers={
            "processor": WorkerConfig(
                class_path="module.Processor",
                priority="normal",
                config={"batch_size": 10}
            )
        }
    )
    
    pm.register_from_config(config)
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional


@dataclass
class QueueConfig:
    """
    Конфигурация очереди процесса.
    
    Attributes:
        maxsize: Максимальный размер очереди (по умолчанию 100)
    """
    maxsize: int = 100


@dataclass
class WorkerConfig:
    """
    Конфигурация воркера процесса.
    
    Attributes:
        class_path: Путь к классу воркера (например, 'module.path.WorkerClass')
        priority: Приоритет воркера (normal, high, low, realtime, batch)
        auto_start: Автоматически запускать воркер при старте процесса
        config: Дополнительная конфигурация воркера
    """
    class_path: str
    priority: str = "normal"
    auto_start: bool = True
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConsoleConfig:
    """
    Конфигурация консоли процесса.
    
    Attributes:
        enabled: Включена ли консоль
        title: Заголовок консоли
        recipient: Получатель консоли (имя процесса или список имен)
    """
    enabled: bool = True
    title: Optional[str] = None
    recipient: Optional[str | list[str]] = None


@dataclass
class ProcessConfig:
    """
    Конфигурация процесса для декларативного создания.
    
    Представляет собой удобный программный способ создания конфигурации процесса
    с валидацией и поддержкой всех возможностей системы.
    
    Attributes:
        name: Имя процесса
        class_path: Путь к классу процесса (например, 'module.path.ProcessClass')
        priority: Приоритет процесса (high, normal, low, above_normal, below_normal)
        enabled: Включен ли процесс (по умолчанию True)
        config: Основная конфигурация процесса
        queues: Словарь конфигураций очередей {queue_name: QueueConfig}
        workers: Словарь конфигураций воркеров {worker_name: WorkerConfig}
        console: Конфигурация консоли процесса
        custom: Дополнительные кастомные настройки
    
    Пример:
        config = ProcessConfig(
            name="ChatProcess",
            class_path="src.Test_example.multiprocess_chat_app.ChatProcess",
            priority="normal",
            queues={
                "messages": QueueConfig(maxsize=100),
                "system": QueueConfig(maxsize=50)
            },
            console=ConsoleConfig(enabled=True, title="Chat Console")
        )
    """
    name: str
    class_path: str
    priority: str = "normal"
    enabled: bool = True
    config: Dict[str, Any] = field(default_factory=dict)
    queues: Dict[str, QueueConfig] = field(default_factory=dict)
    workers: Dict[str, WorkerConfig] = field(default_factory=dict)
    console: Optional[ConsoleConfig] = None
    custom: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Конвертирует ProcessConfig в словарь для использования с ProcessManager.
        
        Returns:
            Словарь конфигурации в формате, совместимом с существующим API
        """
        result = {
            "name": self.name,
            "class": self.class_path,
            "priority": self.priority,
            "enabled": self.enabled,
            "config": self.config.copy()
        }
        
        # Добавляем конфигурацию очередей
        if self.queues:
            result["queues"] = {
                name: {"maxsize": queue_config.maxsize}
                for name, queue_config in self.queues.items()
            }
        
        # Добавляем конфигурацию воркеров
        if self.workers:
            result["workers"] = {
                name: {
                    "class": worker_config.class_path,
                    "priority": worker_config.priority,
                    "auto_start": worker_config.auto_start,
                    "config": worker_config.config.copy()
                }
                for name, worker_config in self.workers.items()
            }
        
        # Добавляем конфигурацию консоли
        if self.console:
            console_dict = {
                "enabled": self.console.enabled
            }
            if self.console.title:
                console_dict["title"] = self.console.title
            if self.console.recipient:
                console_dict["recipient"] = self.console.recipient
            result["console"] = console_dict
        
        # Добавляем кастомные настройки в config
        if self.custom:
            result["config"].update(self.custom)
        
        return result
    
    def validate(self) -> tuple[bool, Optional[str]]:
        """
        Валидирует конфигурацию процесса.
        
        Returns:
            (is_valid, error_message) - True если валидна, иначе False с сообщением об ошибке
        """
        if not self.name:
            return False, "Process name cannot be empty"
        
        if not self.class_path:
            return False, "Process class_path cannot be empty"
        
        if '.' not in self.class_path:
            return False, "Process class_path must be in format 'module.path.ClassName'"
        
        valid_priorities = ['high', 'normal', 'low', 'above_normal', 'below_normal']
        if self.priority not in valid_priorities:
            return False, f"Invalid priority: {self.priority}. Must be one of {valid_priorities}"
        
        # Валидация воркеров
        for worker_name, worker_config in self.workers.items():
            if not worker_config.class_path:
                return False, f"Worker '{worker_name}' class_path cannot be empty"
            if '.' not in worker_config.class_path:
                return False, f"Worker '{worker_name}' class_path must be in format 'module.path.ClassName'"
            
            valid_worker_priorities = ['normal', 'high', 'low', 'realtime', 'batch']
            if worker_config.priority not in valid_worker_priorities:
                return False, f"Worker '{worker_name}' has invalid priority: {worker_config.priority}"
        
        return True, None

