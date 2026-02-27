"""
Ядро процесса - базовая инициализация и жизненный цикл.

Отвечает за:
- Базовую инициализацию процесса
- Управление жизненным циклом (run, stop)
- Хранение базовых атрибутов

ConfigManager создается локально в каждом процессе.
Конфигурация и очереди берутся из ProcessData через shared_resources.
"""

from multiprocessing import Queue
from typing import Dict, Any, Optional


class ProcessCore:
    """
    Ядро процесса - базовая функциональность.
    
    Отвечает только за жизненный цикл и базовые атрибуты.
    
    ConfigManager создается локально в каждом процессе.
    Конфигурация и очереди берутся из ProcessData через shared_resources.
    """
    
    def __init__(
        self, 
        name: str, 
        shared_resources=None, 
        config: dict = None
    ):
        """
        Инициализация ядра процесса.
        
        Args:
            name: Имя процесса
            shared_resources: SharedResourcesManager (легковесный контейнер с ProcessStateRegistry)
            config: Локальная конфигурация процесса (опционально, берется из process_data если не указана)
        """
        self.name = name
        self.shared_resources = shared_resources
        
        # Получаем ProcessData для этого процесса
        process_data = None
        if shared_resources:
            process_data = shared_resources.get_process_data(name)
        
        # Получаем конфигурацию из ProcessData если доступна
        if process_data and process_data.config:
            # Объединяем конфигурацию из process_data с переданной config
            process_config = process_data.config.process.copy()
            if config:
                process_config.update(config)
            self.config = process_config
        else:
            self.config = config or {}
        
        # ConfigManager создается локально в каждом процессе
        # Загружаем конфигурацию из ProcessData если доступна
        from ..Config_module.config_manager import ConfigManager
        self.config_manager = ConfigManager()
        if process_data and process_data.config:
            # Обновляем ConfigManager конфигурацией из ProcessData
            config_dict = process_data.config.to_dict()
            if config_dict.get('process'):
                # Используем update_process_config для обновления конфигурации процессов
                self.config_manager.update_process_config({name: config_dict['process']})
        
        self.stop_process = False

        # Используем очереди из ProcessData если доступны, иначе создаем новые
        if process_data and process_data.queues:
            # Получаем словарь очередей из ProcessData
            # process_data.queues - это QueuesProxy, нужно получить словарь через _queues_dict
            queues_dict = {}
            for queue_type in process_data.queues.keys():
                queue = process_data.get_queue(queue_type)
                if queue:
                    queues_dict[queue_type] = queue
            self.queues = queues_dict if queues_dict else None
        else:
            self.queues = None
        
        # Если очереди не были получены из ProcessData, создаем дефолтные
        if not self.queues:
            self.queues = {
                'system': Queue(maxsize=100),    
                'data': Queue(maxsize=50),       
                'broadcast': Queue(maxsize=20),  
                'custom': Queue(maxsize=20),  
            }
    
    def run(self):
        """
        Запуск процесса.
        
        Должен быть переопределен в ProcessModule для запуска воркеров.
        """
        self.stop_process = False
    
    def stop(self):
        """
        Остановка процесса.
        
        Должен быть переопределен в ProcessModule для корректной остановки.
        """
        self.stop_process = True
    
    def should_stop(self) -> bool:
        """
        Проверка флага остановки.
        
        Returns:
            bool: True если процесс должен остановиться
        """
        return self.stop_process
    
    def register_queue(self, name: str, queue: Queue):
        """
        Регистрация дополнительной очереди.
        
        Args:
            name: Имя очереди
            queue: Экземпляр очереди
        """
        self.queues[name] = queue

