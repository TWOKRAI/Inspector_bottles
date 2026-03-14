"""
Менеджер очередей для межпроцессного взаимодействия.

Набор утилитных методов для работы с очередями процессов.
Все данные хранятся в ProcessStateRegistry (ProcessData), этот класс предоставляет только методы.

ВАЖНО: ProcessStateRegistry является единственным источником истины для очередей.
Этот класс не хранит данные, а работает с данными из ProcessStateRegistry.
"""

from multiprocessing import Queue
from typing import Dict, Any, Optional, List

# Импорт Empty для multiprocessing.Queue
try:
    from multiprocessing.queues import Empty
except ImportError:
    from queue import Empty

from ..Process_module.process_state_registry import ProcessStateRegistry


class QueueManager:
    """
    Менеджер очередей для межпроцессного взаимодействия.
    
    Набор утилитных методов для работы с очередями процессов.
    Все данные хранятся в ProcessStateRegistry (ProcessData), этот класс предоставляет только методы.
    
    ВАЖНО: ProcessStateRegistry является единственным источником истины для очередей.
    Этот класс не хранит данные, а работает с данными из ProcessStateRegistry.
    
    Пример использования:
        queue_manager = QueueManager(process_state_registry)
        queue_manager.create_and_register_queues("process_1", queue_config)
        queue_manager.send_to_queue("process_1", "data", message)
    """
    
    def __init__(self, process_state_registry: ProcessStateRegistry):
        """
        Инициализация менеджера очередей.
        
        Args:
            process_state_registry: ProcessStateRegistry - обязательный параметр,
                                  единственный источник истины для очередей
        """
        if process_state_registry is None:
            raise ValueError("ProcessStateRegistry is required for QueueManager")
        self.process_state_registry = process_state_registry
    
    def create_queues(
        self, 
        queue_config: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> Dict[str, Queue]:
        """
        Создает очереди на основе конфигурации.
        
        Создает только те очереди, которые указаны в конфигурации.
        Если конфигурация пустая или None, возвращает пустой словарь.
        
        Args:
            queue_config: Конфигурация очередей в формате:
                {
                    'system': {'maxsize': 100},
                    'data': {'maxsize': 50},
                    'custom_queue': {'maxsize': 20}
                }
                Если None или пустой словарь, возвращает пустой словарь.
                
        Returns:
            Словарь очередей {queue_type: Queue}
        """
        queues = {}
        
        if not queue_config:
            return queues
        
        # Создаем только указанные очереди
        for queue_type, config in queue_config.items():
            maxsize = config.get('maxsize', 0) if isinstance(config, dict) else 0
            queues[queue_type] = Queue(maxsize=maxsize)
        
        return queues
    
    def register_process_queues(self, process_name: str, queues: Dict[str, Queue]) -> bool:
        """
        Регистрация очередей процесса в ProcessStateRegistry.
        
        Добавляет очереди в ProcessData через ProcessStateRegistry.
        
        Args:
            process_name: Имя процесса
            queues: Словарь очередей процесса {queue_type: Queue}
            
        Returns:
            bool: True если регистрация успешна
        """
        try:
            # Добавляем очереди в ProcessStateRegistry (единственный источник истины)
            for queue_type, queue in queues.items():
                self.process_state_registry.add_queue(process_name, queue_type, queue)
            
            print(f"QueueManager: Registered {len(queues)} queues for process '{process_name}'")
            return True
        except Exception as e:
            print(f"QueueManager: Failed to register queues for {process_name}: {e}")
            return False
    
    def create_and_register_queues(
        self,
        process_name: str,
        queue_config: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> bool:
        """
        Создает и регистрирует очереди для процесса одной операцией.
        
        Args:
            process_name: Имя процесса
            queue_config: Конфигурация очередей
            
        Returns:
            bool: True если успешно
        """
        queues = self.create_queues(queue_config)
        if queues:
            return self.register_process_queues(process_name, queues)
        return False
    
    def get_queue(self, process_name: str, queue_type: str) -> Optional[Queue]:
        """
        Получение очереди по имени процесса и типу очереди.
        
        Получает очередь из ProcessStateRegistry (единственный источник истины).
        
        Args:
            process_name: Имя процесса
            queue_type: Тип очереди
            
        Returns:
            Queue или None если не найдена
        """
        return self.process_state_registry.get_queue(process_name, queue_type)
    
    def get_process_queues(self, process_name: str) -> Dict[str, Queue]:
        """
        Получение всех очередей процесса.
        
        Получает очереди из ProcessData через ProcessStateRegistry.
        
        Args:
            process_name: Имя процесса
            
        Returns:
            Словарь очередей {queue_type: Queue} или пустой словарь
        """
        process_data = self.process_state_registry.get_process_data(process_name)
        if process_data:
            # Возвращаем словарь очередей из ProcessData
            return dict(process_data.queues.items())
        return {}
    
    def send_to_queue(self, process_name: str, queue_type: str, data: Any) -> bool:
        """
        Отправка данных в конкретную очередь процесса.
        
        Args:
            process_name: Имя процесса
            queue_type: Тип очереди
            data: Данные для отправки
            
        Returns:
            bool: True если успешно
        """
        try:
            queue = self.get_queue(process_name, queue_type)
            if queue is None:
                return False
            
            # Если очередь полна, удаляем старый элемент
            self.remove_old_if_full(queue)
            
            queue.put(data)
            return True
            
        except Exception as e:
            print(f"QueueManager: Failed to send to {process_name}.{queue_type}: {e}")
            return False
    
    def broadcast_message(
        self, 
        data: Any, 
        queue_type: str = "system", 
        exclude_process: Optional[str] = None
    ) -> int:
        """
        Рассылка сообщения во все процессы.
        
        Args:
            data: Данные для рассылки
            queue_type: Тип очереди для рассылки
            exclude_process: Имя процесса для исключения из рассылки
            
        Returns:
            int: Количество процессов, которым доставлено сообщение
        """
        delivered_count = 0
        process_names = self.process_state_registry.get_process_names()
        
        for process_name in process_names:
            if process_name == exclude_process:
                continue
            if self.send_to_queue(process_name, queue_type, data):
                delivered_count += 1
        
        return delivered_count
    
    def get_registered_processes(self) -> List[str]:
        """
        Получение списка процессов с зарегистрированными очередями.
        
        Returns:
            Список имен процессов
        """
        return self.process_state_registry.get_process_names()
    
    def get_queue_sizes(self) -> Dict[str, Dict[str, int]]:
        """
        Получить размеры всех очередей всех процессов.
        
        Returns:
            Словарь: {process_name: {queue_type: size}}
        """
        sizes = {}
        all_process_data = self.process_state_registry.get_all_process_data()
        
        for process_name, process_data in all_process_data.items():
            sizes[process_name] = {}
            for queue_type, queue in process_data.queues.items():
                try:
                    sizes[process_name][queue_type] = queue.qsize()
                except (NotImplementedError, OSError, AttributeError):
                    sizes[process_name][queue_type] = 0
                except Exception as e:
                    sizes[process_name][queue_type] = -1  # Ошибка
        
        return sizes
    
    def clear_all_queues(self):
        """Очистить все очереди всех процессов."""
        all_process_data = self.process_state_registry.get_all_process_data()
        
        for process_name, process_data in all_process_data.items():
            for queue_type, queue in process_data.queues.items():
                self.clear_queue(queue, keep_elements=0)
        
        print('QueueManager: Очистка всех очередей завершена')
    
    def clear_queue(self, queue: Queue, keep_elements: int = 0):
        """
        Надежная очистка очереди для всех платформ.
        
        Args:
            queue: Очередь для очистки
            keep_elements: Количество элементов для сохранения (с конца)
        """
        saved_items = []
        try:
            # Сохраняем последние keep_elements элементов
            while not queue.empty():
                try:
                    item = queue.get_nowait()
                    saved_items.append(item)
                except Empty:
                    break
            
            # Оставляем только последние элементы
            if keep_elements > 0:
                saved_items = saved_items[-keep_elements:]
            
            # Возвращаем сохраненные элементы
            for item in saved_items:
                queue.put(item)
                
        except Exception as e:
            print(f"QueueManager: Warning - Queue clearing failed: {e}")
    
    def remove_old_if_full(self, queue: Queue):
        """
        Удалить старые данные, если очередь заполнена.
        
        Args:
            queue: Очередь для проверки
        """
        if queue.full():
            try:
                queue.get_nowait()
            except Empty:
                pass

