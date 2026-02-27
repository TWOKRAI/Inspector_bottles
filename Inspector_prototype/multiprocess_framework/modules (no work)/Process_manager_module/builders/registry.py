"""
ProcessRegistry - реестр для автоматической регистрации декорированных процессов.

Собирает метаданные из декорированных классов (@process, @worker, @queue)
и автоматически регистрирует их в ProcessManager.

Пример использования:
    from ...Process_manager_module.builders import ProcessRegistry
    
    registry = ProcessRegistry()
    
    # Регистрация декорированного процесса
    registry.register_decorated(ChatProcess)
    
    # Или автоматическая регистрация всех процессов из модуля
    registry.register_from_module('src.Test_example.multiprocess_chat_app')
    
    # Применение к ProcessManager
    registry.apply_to(pm)
"""

import inspect
import importlib
from typing import Dict, Any, Optional, Type, List
from ..process.manager_process import ProcessManager
from .decorators import (
    get_process_metadata,
    get_worker_metadata,
    get_queue_metadata
)
from .configs import ProcessConfig, QueueConfig, WorkerConfig, ConsoleConfig


class ProcessRegistry:
    """
    Реестр для автоматической регистрации декорированных процессов.
    
    Собирает метаданные из декорированных классов и конвертирует их
    в формат, совместимый с ProcessManager.
    
    Attributes:
        processes: Словарь зарегистрированных процессов {name: config_dict}
    """
    
    def __init__(self):
        """Инициализация реестра."""
        self.processes: Dict[str, Dict[str, Any]] = {}
    
    def register_decorated(self, process_class: Type) -> bool:
        """
        Регистрирует декорированный класс процесса.
        
        Собирает метаданные из декораторов @process, @worker, @queue
        и создает конфигурацию процесса.
        
        Args:
            process_class: Класс процесса, декорированный @process
        
        Returns:
            True если регистрация успешна, False если класс не декорирован
        
        Пример:
            @process(name="ChatProcess", priority="normal")
            class ChatProcess(ProcessModule):
                pass
            
            registry = ProcessRegistry()
            registry.register_decorated(ChatProcess)
        """
        # Получаем метаданные процесса
        process_metadata = get_process_metadata(process_class)
        if not process_metadata:
            return False
        
        # Создаем базовую конфигурацию процесса
        config = {
            "name": process_metadata["name"],
            "class": process_metadata["class_path"],
            "priority": process_metadata.get("priority", "normal"),
            "enabled": process_metadata.get("enabled", True),
            "config": process_metadata.get("config", {}),
            "queues": {},
            "workers": {}
        }
        
        # Собираем метаданные воркеров из методов класса
        for name, method in inspect.getmembers(process_class, predicate=inspect.isfunction):
            worker_metadata = get_worker_metadata(method)
            if worker_metadata:
                config["workers"][worker_metadata["name"]] = {
                    "class": worker_metadata.get("class_path", ""),
                    "priority": worker_metadata.get("priority", "normal"),
                    "auto_start": worker_metadata.get("auto_start", True),
                    "config": worker_metadata.get("config", {})
                }
            
            queue_metadata = get_queue_metadata(method)
            if queue_metadata:
                config["queues"][queue_metadata["name"]] = {
                    "maxsize": queue_metadata.get("maxsize", 100)
                }
        
        # Добавляем конфигурацию консоли если указана
        if "console" in process_metadata:
            config["console"] = process_metadata["console"]
        
        # Сохраняем в реестре
        self.processes[config["name"]] = config
        
        return True
    
    def register_from_module(self, module_path: str) -> int:
        """
        Автоматически регистрирует все декорированные процессы из модуля.
        
        Импортирует модуль и ищет все классы, декорированные @process.
        
        Args:
            module_path: Путь к модулю (например, 'src.Test_example.multiprocess_chat_app')
        
        Returns:
            Количество зарегистрированных процессов
        
        Пример:
            registry = ProcessRegistry()
            count = registry.register_from_module('src.Test_example.multiprocess_chat_app')
        """
        try:
            module = importlib.import_module(module_path)
            registered_count = 0
            
            # Ищем все классы в модуле
            for name, obj in inspect.getmembers(module, predicate=inspect.isclass):
                # Проверяем, что класс декорирован @process
                if get_process_metadata(obj):
                    if self.register_decorated(obj):
                        registered_count += 1
            
            return registered_count
        
        except ImportError as e:
            raise ImportError(f"Failed to import module '{module_path}': {e}")
    
    def register_from_config(self, config: ProcessConfig) -> bool:
        """
        Регистрирует процесс из ProcessConfig.
        
        Args:
            config: Экземпляр ProcessConfig
        
        Returns:
            True если регистрация успешна
        
        Пример:
            config = ProcessConfig(
                name="MyProcess",
                class_path="module.MyProcess",
                priority="high"
            )
            registry.register_from_config(config)
        """
        # Валидация конфигурации
        is_valid, error = config.validate()
        if not is_valid:
            raise ValueError(f"Invalid ProcessConfig: {error}")
        
        # Конвертируем в словарь
        config_dict = config.to_dict()
        
        # Сохраняем в реестре
        self.processes[config_dict["name"]] = config_dict
        
        return True
    
    def apply_to(self, process_manager: ProcessManager) -> int:
        """
        Применяет все зарегистрированные процессы к ProcessManager.
        
        Регистрирует все процессы из реестра в ProcessManager через существующие методы.
        
        Args:
            process_manager: Экземпляр ProcessManager
        
        Returns:
            Количество успешно зарегистрированных процессов
        
        Пример:
            registry = ProcessRegistry()
            registry.register_decorated(ChatProcess)
            registry.apply_to(pm)
        """
        registered_count = 0
        
        for process_name, config in self.processes.items():
            try:
                # Используем существующий метод register_process через core
                success = process_manager.core.create_process(
                    name=config["name"],
                    class_path=config["class"],
                    config=config,
                    priority=config.get("priority", "normal")
                )
                
                if success:
                    registered_count += 1
                    
                    # Регистрируем воркеры если есть
                    workers = config.get("workers", {})
                    for worker_name, worker_config in workers.items():
                        process_manager.core.register_worker(
                            process_name=process_name,
                            worker_name=worker_name,
                            worker_class_path=worker_config.get("class", ""),
                            config=worker_config.get("config", {}),
                            priority=worker_config.get("priority", "normal"),
                            auto_start=worker_config.get("auto_start", True)
                        )
                    
                    # Регистрируем очереди если есть
                    queues = config.get("queues", {})
                    for queue_name, queue_config in queues.items():
                        process_manager.core.register_queue(
                            process_name=process_name,
                            queue_name=queue_name,
                            maxsize=queue_config.get("maxsize", 100)
                        )
            
            except Exception as e:
                # Логируем ошибку но продолжаем регистрацию других процессов
                process_manager.log("ERROR", f"Failed to register process '{process_name}': {e}", "registry")
        
        return registered_count
    
    def clear(self):
        """Очищает реестр от всех зарегистрированных процессов."""
        self.processes.clear()
    
    def get_process_config(self, process_name: str) -> Optional[Dict[str, Any]]:
        """
        Получить конфигурацию процесса из реестра.
        
        Args:
            process_name: Имя процесса
        
        Returns:
            Словарь конфигурации или None если процесс не найден
        """
        return self.processes.get(process_name)
    
    def get_all_configs(self) -> Dict[str, Dict[str, Any]]:
        """
        Получить все конфигурации процессов из реестра.
        
        Returns:
            Словарь всех конфигураций {process_name: config}
        """
        return self.processes.copy()

