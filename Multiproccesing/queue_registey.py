from multiprocessing import Queue
from typing import Dict, Any, Optional, List
from queue import Empty

class QueueRegistry:
    """
    Центральный реестр очередей для межпроцессного взаимодействия
    """
    
    def __init__(self):
        self.registered_queues: Dict[str, Dict[str, Queue]] = {}
        # Структура: {process_name: {queue_type: Queue}}
    
    def register_process_queues(self, process_name: str, queues: Dict[str, Queue]) -> bool:
        """Регистрация очередей процесса в реестре"""
        try:
            if process_name not in self.registered_queues:
                self.registered_queues[process_name] = {}
            
            self.registered_queues[process_name].update(queues)
            print(f"QueueRegistry: Registered {len(queues)} queues for process '{process_name}'")
            return True
        except Exception as e:
            print(f"QueueRegistry: Failed to register queues for {process_name}: {e}")
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


    def get_queue_sizes(self):
        """Получить размеры всех очередей."""
        return {name: queue.qsize() for name, queue in self.queues.items()}


    def clear_all_queues(self):
        """Очистить все очереди."""
        for queue in self.queues.values():
            self.clear_queue(queue, keep_elements=0)

        print('Очистка всех очередей')

