from multiprocessing import Queue
from typing import Dict, Any, Optional, List

# Импорт Empty для multiprocessing.Queue
try:
    from multiprocessing.queues import Empty
except ImportError:
    from queue import Empty


class QueueRegistry:
    """
    Центральный реестр очередей для межпроцессного взаимодействия.
    
    Отвечает за создание, регистрацию и управление очередями для всех процессов.
    Создает только те очереди, которые указаны в конфигурации.
    
    Интегрирован с ProcessStateRegistry для хранения очередей в ProcessData.
    """
    
    def __init__(self, process_state_registry=None):
        """
        Инициализация реестра очередей.
        
        Args:
            process_state_registry: Опциональная ссылка на ProcessStateRegistry
                                   для интеграции с ProcessData
        """
        self.registered_queues: Dict[str, Dict[str, Queue]] = {}
        # Структура: {process_name: {queue_type: Queue}}
        # Дублируется в ProcessData для удобного доступа
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
        Регистрация очередей процесса в реестре.
        
        Также добавляет очереди в ProcessData через ProcessStateRegistry если доступен.
        
        Args:
            process_name: Имя процесса
            queues: Словарь очередей процесса {queue_type: Queue}
            
        Returns:
            bool: True если регистрация успешна
        """
        try:
            if process_name not in self.registered_queues:
                self.registered_queues[process_name] = {}
            
            self.registered_queues[process_name].update(queues)
            
            # Интеграция с ProcessStateRegistry - добавляем очереди в ProcessData
            if self.process_state_registry:
                for queue_type, queue in queues.items():
                    self.process_state_registry.add_queue(process_name, queue_type, queue)
            
            print(f"QueueRegistry: Registered {len(queues)} queues for process '{process_name}'")
            return True
        except Exception as e:
            print(f"QueueRegistry: Failed to register queues for {process_name}: {e}")
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
    
    def unregister_process(self, process_name: str) -> bool:
        """Удаление процесса из реестра"""
        if process_name in self.registered_queues:
            del self.registered_queues[process_name]
            print(f"QueueRegistry: Unregistered process '{process_name}'")
            return True
        return False
    
    def send_to_queue(self, process_name: str, queue_type: str, data: Any) -> bool:
        """Отправка данных в конкретную очередь процесса"""
        try:
            if process_name not in self.registered_queues:
                return False
            
            if queue_type not in self.registered_queues[process_name]:
                return False
            
            queue = self.registered_queues[process_name][queue_type]
            
            # Если очередь полна, удаляем старый элемент
            self.remove_old_if_full(queue)
            
            queue.put(data)
            return True
            
        except Exception as e:
            print(f"QueueRegistry: Failed to send to {process_name}.{queue_type}: {e}")
            return False
    
    def get_queue(self, process_name: str, queue_type: str) -> Optional[Queue]:
        """Получение очереди по имени процесса и типу очереди"""
        return self.registered_queues.get(process_name, {}).get(queue_type)
    
    def get_registered_processes(self) -> List[str]:
        """Получение списка зарегистрированных процессов"""
        return list(self.registered_queues.keys())
    
    def get_process_queues(self, process_name: str) -> Dict[str, Queue]:
        """Получение всех очередей процесса"""
        return self.registered_queues.get(process_name, {})
    
    def broadcast_message(self, data: Any, queue_type: str = "system", exclude_process: str = None) -> int:
        """Рассылка сообщения во все процессы"""
        delivered_count = 0
        for process_name in self.registered_queues:
            if process_name == exclude_process:
                continue
            if self.send_to_queue(process_name, queue_type, data):
                delivered_count += 1
        return delivered_count

    def remove_old_if_full(self, queue):
        """Удалить старые данные, если очередь заполнена."""
        if queue.full():
            try:
                queue.get_nowait()
            except Empty:
                pass

    def get_queue_sizes(self) -> Dict[str, Dict[str, int]]:
        """
        Получить размеры всех очередей всех процессов.
        
        Returns:
            Словарь: {process_name: {queue_type: size}}
        """
        sizes = {}
        for process_name, queues in self.registered_queues.items():
            sizes[process_name] = {}
            for queue_type, queue in queues.items():
                try:
                    sizes[process_name][queue_type] = queue.qsize()
                except (NotImplementedError, OSError, AttributeError):
                    sizes[process_name][queue_type] = 0
                except Exception as e:
                    sizes[process_name][queue_type] = -1  # Ошибка
        return sizes

    def clear_all_queues(self):
        """Очистить все очереди всех процессов."""
        for process_name, queues in self.registered_queues.items():
            for queue_type, queue in queues.items():
                self.clear_queue(queue, keep_elements=0)
        print('Очистка всех очередей')
        
    def clear_queue(self, queue: Queue, keep_elements: int = 0):
        """Надежная очистка очереди для всех платформ"""
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
            print(f"Warning: Queue clearing failed: {e}")
