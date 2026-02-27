"""
Реестр очередей для межпроцессного взаимодействия (Refactored).

Наследуется от BaseManager и использует ObservableMixin для единообразия со всеми менеджерами системы.
Интегрируется с ProcessStateRegistry для хранения очередей в ProcessData.
Данные хранятся в data_schema через ProcessData.
"""

from multiprocessing import Queue
from typing import Dict, Any, Optional, List

from ...base_manager import BaseManager, ObservableMixin

# Импорт Empty для multiprocessing.Queue
try:
    from multiprocessing.queues import Empty
except ImportError:
    from queue import Empty


class QueueRegistry(BaseManager, ObservableMixin):
    """
    Центральный реестр очередей для межпроцессного взаимодействия (Refactored).
    
    Наследуется от BaseManager и использует ObservableMixin для:
    - Единообразия со всеми менеджерами системы
    - Автоматического логирования через ObservableMixin
    - Стандартного жизненного цикла (initialize/shutdown)
    
    Отвечает за создание, регистрацию и управление очередями для всех процессов.
    Интегрирован с ProcessStateRegistry для хранения очередей в ProcessData.
    Данные хранятся в data_schema через ProcessData.
    
    Attributes:
        manager_name: Имя менеджера
        process_state_registry: ProcessStateRegistry для интеграции с ProcessData
        registered_queues: Реестр очередей {process_name: {queue_type: Queue}}
    """
    
    def __init__(
        self,
        manager_name: str = "QueueRegistry",
        process: Optional[Any] = None,
        process_state_registry=None,
        logger=None,
        **kwargs
    ):
        """
        Инициализация реестра очередей.
        
        Args:
            manager_name: Имя менеджера
            process: Ссылка на родительский процесс (опционально)
            process_state_registry: ProcessStateRegistry для интеграции с ProcessData
            logger: Логгер (опционально, используется через ObservableMixin)
            **kwargs: Дополнительные параметры для ObservableMixin
        """
        # Инициализация BaseManager
        BaseManager.__init__(self, manager_name=manager_name, process=process)
        
        # Инициализация ObservableMixin
        managers = kwargs.get('managers', {})
        if logger and 'logger' not in managers:
            managers['logger'] = logger
        
        config = kwargs.get('config', {})
        auto_proxy = kwargs.get('auto_proxy', True)
        
        ObservableMixin.__init__(
            self,
            managers=managers,
            config=config,
            auto_proxy=auto_proxy
        )
        
        # Реестр очередей {process_name: {queue_type: Queue}}
        self.registered_queues: Dict[str, Dict[str, Queue]] = {}
        
        # ProcessStateRegistry для интеграции с ProcessData
        self.process_state_registry = process_state_registry
        
        # Статистика
        self._stats = {
            'created': 0,
            'registered': 0,
            'removed': 0,
            'errors': 0
        }
    
    # ========================================================================
    # РЕАЛИЗАЦИЯ BaseManager - ЖИЗНЕННЫЙ ЦИКЛ
    # ========================================================================
    
    def initialize(self) -> bool:
        """
        Инициализация реестра очередей.
        
        Returns:
            bool: True если инициализация успешна
        """
        try:
            self.is_initialized = True
            self._log_info(f"QueueRegistry '{self.manager_name}' initialized")
            return True
        except Exception as e:
            self._log_error(f"Failed to initialize QueueRegistry: {e}")
            return False
    
    def shutdown(self) -> bool:
        """
        Завершение работы реестра очередей.
        
        Очищает реестр очередей.
        
        Returns:
            bool: True если завершение успешно
        """
        try:
            # Очищаем реестр
            self.registered_queues.clear()
            
            self.is_initialized = False
            self._log_info("QueueRegistry shutdown completed")
            return True
        except Exception as e:
            self._log_error(f"Error during QueueRegistry shutdown: {e}")
            return False
    
    # ========================================================================
    # ОСНОВНОЙ API - СОЗДАНИЕ И РЕГИСТРАЦИЯ ОЧЕРЕДЕЙ
    # ========================================================================
    
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
        
        try:
            # Создаем только указанные очереди
            for queue_type, config in queue_config.items():
                maxsize = config.get('maxsize', 0) if isinstance(config, dict) else 0
                queues[queue_type] = Queue(maxsize=maxsize)
                self._stats['created'] += 1
            
            self._log_debug(f"Created {len(queues)} queues from config")
        except Exception as e:
            self._log_error(f"Failed to create queues: {e}")
            self._stats['errors'] += 1
        
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
            self._stats['registered'] += len(queues)
            
            # Интеграция с ProcessStateRegistry - добавляем очереди в ProcessData
            if self.process_state_registry:
                for queue_type, queue in queues.items():
                    self.process_state_registry.add_queue(process_name, queue_type, queue)
            
            self._log_debug(f"Registered {len(queues)} queues for process '{process_name}'")
            return True
        except Exception as e:
            self._log_error(f"Failed to register queues for {process_name}: {e}")
            self._stats['errors'] += 1
            return False
    
    def create_and_register_queues(
        self,
        process_name: str,
        queue_config: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> Dict[str, Queue]:
        """
        Создает и регистрирует очереди для процесса.
        
        Args:
            process_name: Имя процесса
            queue_config: Конфигурация очередей
        
        Returns:
            Словарь созданных очередей {queue_type: Queue}
        """
        queues = self.create_queues(queue_config)
        if queues:
            self.register_process_queues(process_name, queues)
        return queues
    
    def get_queue(self, process_name: str, queue_type: str) -> Optional[Queue]:
        """
        Получить очередь процесса.
        
        Args:
            process_name: Имя процесса
            queue_type: Тип очереди
        
        Returns:
            Queue или None если не найдена
        """
        if process_name in self.registered_queues:
            return self.registered_queues[process_name].get(queue_type)
        return None
    
    def get_process_queues(self, process_name: str) -> Dict[str, Queue]:
        """
        Получить все очереди процесса.
        
        Args:
            process_name: Имя процесса
        
        Returns:
            Словарь очередей {queue_type: Queue}
        """
        return self.registered_queues.get(process_name, {})
    
    def remove_process_queues(self, process_name: str) -> bool:
        """
        Удалить все очереди процесса из реестра.
        
        Args:
            process_name: Имя процесса
        
        Returns:
            bool: True если удаление успешно
        """
        if process_name in self.registered_queues:
            queues_count = len(self.registered_queues[process_name])
            del self.registered_queues[process_name]
            self._stats['removed'] += queues_count
            self._log_debug(f"Removed {queues_count} queues for process '{process_name}'")
            return True
        return False
    
    def send_to_queue(
        self,
        process_name: str,
        queue_type: str,
        message: Any,
        timeout: float = 0.0
    ) -> bool:
        """
        Отправить сообщение в очередь процесса.
        
        Args:
            process_name: Имя процесса
            queue_type: Тип очереди
            message: Сообщение для отправки (любой тип)
            timeout: Таймаут отправки (0 = non-blocking)
        
        Returns:
            bool: True если отправка успешна
        """
        queue = self.get_queue(process_name, queue_type)
        if not queue:
            self._log_warning(f"Queue '{queue_type}' not found for process '{process_name}'")
            return False
        
        try:
            # Если очередь полна, удаляем старый элемент
            self.remove_old_if_full(queue)
            
            if timeout > 0:
                queue.put(message, timeout=timeout)
            else:
                queue.put_nowait(message)
            return True
        except Exception as e:
            self._log_error(f"Failed to send message to queue '{queue_type}' of '{process_name}': {e}")
            self._stats['errors'] += 1
            return False
    
    def receive_from_queue(
        self,
        process_name: str,
        queue_type: str,
        timeout: float = 0.0
    ) -> Optional[Any]:
        """
        Получить сообщение из очереди процесса.
        
        Args:
            process_name: Имя процесса
            queue_type: Тип очереди
            timeout: Таймаут получения (0 = non-blocking)
        
        Returns:
            Сообщение (любой тип) или None если очередь пуста
        """
        queue = self.get_queue(process_name, queue_type)
        if not queue:
            return None
        
        try:
            if timeout > 0:
                return queue.get(timeout=timeout)
            else:
                return queue.get_nowait()
        except Empty:
            return None
        except Exception as e:
            self._log_error(f"Failed to receive message from queue '{queue_type}' of '{process_name}': {e}")
            self._stats['errors'] += 1
            return None
    
    def broadcast_message(
        self,
        message: Any,
        queue_type: str = "system",
        exclude_process: Optional[str] = None
    ) -> int:
        """
        Рассылка сообщения всем процессам через указанный тип очереди.
        
        Args:
            message: Сообщение для рассылки (любой тип)
            queue_type: Тип очереди для рассылки (по умолчанию "system")
            exclude_process: Имя процесса для исключения из рассылки
        
        Returns:
            Количество успешных доставок
        """
        sent_count = 0
        
        for process_name in self.registered_queues.keys():
            if exclude_process and process_name == exclude_process:
                continue
            
            if self.send_to_queue(process_name, queue_type, message):
                sent_count += 1
        
        return sent_count
    
    def get_registered_processes(self) -> List[str]:
        """
        Получение списка зарегистрированных процессов.
        
        Returns:
            Список имен процессов
        """
        return list(self.registered_queues.keys())
    
    # ========================================================================
    # УТИЛИТЫ ДЛЯ РАБОТЫ С ОЧЕРЕДЯМИ
    # ========================================================================
    
    def clear_queue(self, queue: Queue, keep_elements: int = 0):
        """
        Надежная очистка очереди для всех платформ.
        
        На Windows queue.empty() ненадежен, поэтому используем цикл с get_nowait()
        и обработкой Empty исключения.
        
        Args:
            queue: Очередь для очистки
            keep_elements: Количество элементов для сохранения (с конца)
        """
        saved_items = []
        try:
            # Получаем все элементы из очереди (надежный способ для всех платформ)
            # Используем цикл с обработкой Empty вместо queue.empty()
            max_iterations = 10000  # Защита от бесконечного цикла
            iteration = 0
            while iteration < max_iterations:
                try:
                    item = queue.get_nowait()
                    saved_items.append(item)
                    iteration += 1
                except Empty:
                    break
            
            # Оставляем только последние элементы
            if keep_elements > 0 and len(saved_items) > keep_elements:
                saved_items = saved_items[-keep_elements:]
            
            # Возвращаем сохраненные элементы обратно в очередь
            for item in saved_items:
                queue.put(item)
        
        except Exception as e:
            self._log_error(f"Queue clearing failed: {e}")
            self._stats['errors'] += 1
    
    def clear_all_queues(self):
        """
        Очистить все очереди всех процессов.
        """
        for process_name, queues in self.registered_queues.items():
            for queue_type, queue in queues.items():
                self.clear_queue(queue, keep_elements=0)
        
        self._log_info("Очистка всех очередей завершена")
    
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
                    self._log_error(f"Error getting queue size: {e}")
                    sizes[process_name][queue_type] = -1  # Ошибка
        
        return sizes
    
    # ========================================================================
    # СТАТИСТИКА
    # ========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Получить статистику реестра очередей.
        
        Интегрируется со статистикой BaseManager и ObservableMixin.
        """
        stats = super().get_stats() if hasattr(super(), 'get_stats') else {}
        
        # Подсчитываем общее количество очередей
        total_queues = sum(len(queues) for queues in self.registered_queues.values())
        
        queue_stats = {
            'created': self._stats['created'],
            'registered': self._stats['registered'],
            'removed': self._stats['removed'],
            'errors': self._stats['errors'],
            'total_queues': total_queues,
            'processes_count': len(self.registered_queues),
            'processes': list(self.registered_queues.keys())
        }
        
        if isinstance(stats, dict):
            stats['queues'] = queue_stats
        else:
            stats = {'queues': queue_stats}
        
        return stats


