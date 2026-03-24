"""
Базовые интерфейсы для всех компонентов фреймворка.

Определяет контракты для всех модулей системы.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Callable
from multiprocessing import Queue, Event


class IManager(ABC):
    """Базовый интерфейс для всех менеджеров."""
    
    @property
    @abstractmethod
    def manager_name(self) -> str:
        """Уникальное имя менеджера."""
        pass
    
    @abstractmethod
    def initialize(self) -> bool:
        """
        Инициализация менеджера.
        
        Returns:
            True если инициализация успешна
        """
        pass
    
    @abstractmethod
    def shutdown(self) -> bool:
        """
        Корректное завершение работы менеджера.
        
        Returns:
            True если завершение успешно
        """
        pass


class IAdapter(ABC):
    """Базовый интерфейс для всех адаптеров."""
    
    @property
    @abstractmethod
    def adapter_name(self) -> str:
        """Уникальное имя адаптера."""
        pass
    
    @property
    @abstractmethod
    def manager(self) -> Optional[IManager]:
        """Ссылка на менеджер."""
        pass
    
    @abstractmethod
    def setup(self) -> bool:
        """
        Настройка адаптера.
        
        Returns:
            True если настройка успешна
        """
        pass


class IProcess(ABC):
    """Базовый интерфейс для всех процессов."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Имя процесса."""
        pass
    
    @abstractmethod
    def run(self) -> None:
        """Запуск процесса."""
        pass
    
    @abstractmethod
    def stop(self) -> None:
        """Остановка процесса."""
        pass
    
    @abstractmethod
    def should_stop(self) -> bool:
        """
        Проверка флага остановки.
        
        Returns:
            True если процесс должен остановиться
        """
        pass


class IMessage(ABC):
    """Интерфейс для сообщений."""
    
    @property
    @abstractmethod
    def id(self) -> str:
        """Уникальный ID сообщения."""
        pass
    
    @property
    @abstractmethod
    def type(self) -> str:
        """Тип сообщения."""
        pass
    
    @property
    @abstractmethod
    def sender(self) -> str:
        """Отправитель сообщения."""
        pass
    
    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """
        Конвертация сообщения в словарь.
        
        Returns:
            Словарь с данными сообщения
        """
        pass


class IRouter(ABC):
    """Интерфейс для роутера (нервная система)."""
    
    @abstractmethod
    def register_channel(self, channel: 'IMessageChannel') -> bool:
        """
        Регистрация канала.
        
        Args:
            channel: Канал для регистрации
            
        Returns:
            True если регистрация успешна
        """
        pass
    
    @abstractmethod
    def send(self, message: IMessage) -> Dict[str, Any]:
        """
        Отправка сообщения через роутер.
        
        Args:
            message: Сообщение для отправки
            
        Returns:
            Результат отправки
        """
        pass
    
    @abstractmethod
    def receive(self, channel_name: str, timeout: float = 0.0) -> List[Dict[str, Any]]:
        """
        Получение сообщений из канала.
        
        Args:
            channel_name: Имя канала
            timeout: Таймаут ожидания
            
        Returns:
            Список полученных сообщений
        """
        pass


class IMessageChannel(ABC):
    """Интерфейс для каналов сообщений."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Уникальное имя канала."""
        pass
    
    @property
    @abstractmethod
    def channel_type(self) -> str:
        """Тип канала (queue, log, database, etc)."""
        pass
    
    @abstractmethod
    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Отправить сообщение через канал.
        
        Args:
            message: Сообщение для отправки
            
        Returns:
            Результат отправки
        """
        pass
    
    @abstractmethod
    def poll(self, timeout: float = 0.0) -> List[Dict[str, Any]]:
        """
        Опрос канала для получения сообщений.
        
        Args:
            timeout: Таймаут опроса (0 = non-blocking)
            
        Returns:
            Список полученных сообщений
        """
        pass


class ISharedResources(ABC):
    """Интерфейс для менеджера общих ресурсов."""
    
    @abstractmethod
    def get_process_data(self, process_name: str) -> Optional[Any]:
        """
        Получить ProcessData процесса.
        
        Args:
            process_name: Имя процесса
            
        Returns:
            ProcessData или None
        """
        pass
    
    @abstractmethod
    def get_all_process_data(self) -> Dict[str, Any]:
        """
        Получить все ProcessData.
        
        Returns:
            Словарь {process_name: ProcessData}
        """
        pass
    
    @property
    @abstractmethod
    def process_state_registry(self) -> 'IProcessStateRegistry':
        """Реестр состояний процессов."""
        pass
    
    @property
    @abstractmethod
    def event_manager(self) -> 'IEventManager':
        """Менеджер событий."""
        pass


class IProcessStateRegistry(ABC):
    """Интерфейс для реестра состояний процессов."""
    
    @abstractmethod
    def register_process(
        self,
        process_name: str,
        initial_state: Optional[Dict[str, Any]] = None,
        config: Optional[Any] = None
    ) -> bool:
        """
        Зарегистрировать процесс.
        
        Args:
            process_name: Имя процесса
            initial_state: Начальное состояние
            config: Конфигурация процесса
            
        Returns:
            True если регистрация успешна
        """
        pass
    
    @abstractmethod
    def get_process_data(self, process_name: str) -> Optional[Any]:
        """
        Получить ProcessData процесса.
        
        Args:
            process_name: Имя процесса
            
        Returns:
            ProcessData или None
        """
        pass
    
    @abstractmethod
    def update_state(
        self,
        process_name: str,
        status: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Обновить состояние процесса.
        
        Args:
            process_name: Имя процесса
            status: Новый статус
            metadata: Метаданные
            
        Returns:
            True если обновление успешно
        """
        pass


class IEventManager(ABC):
    """Интерфейс для менеджера событий."""
    
    @abstractmethod
    def emit_event(
        self,
        event_type: Any,
        process_name: Optional[str] = None,
        **kwargs
    ) -> bool:
        """
        Отправить событие.
        
        Args:
            event_type: Тип события
            process_name: Имя процесса (опционально)
            **kwargs: Дополнительные данные события
            
        Returns:
            True если событие отправлено
        """
        pass
    
    @abstractmethod
    def subscribe(
        self,
        event_type: Any,
        callback: Callable
    ) -> bool:
        """
        Подписаться на события.
        
        Args:
            event_type: Тип события
            callback: Функция обратного вызова
            
        Returns:
            True если подписка успешна
        """
        pass


class IDataSchema(ABC):
    """Интерфейс для системы данных (ДНК)."""
    
    @abstractmethod
    def register_schema(
        self,
        schema_name: str,
        schema_class: type,
        version: str = "1.0.0"
    ) -> bool:
        """
        Зарегистрировать схему данных.
        
        Args:
            schema_name: Имя схемы
            schema_class: Класс схемы
            version: Версия схемы
            
        Returns:
            True если регистрация успешна
        """
        pass
    
    @abstractmethod
    def create_model(
        self,
        schema_name: str,
        data: Dict[str, Any]
    ) -> Any:
        """
        Создать модель данных по схеме.
        
        Args:
            schema_name: Имя схемы
            data: Данные для модели
            
        Returns:
            Экземпляр модели
        """
        pass


class IWorker(ABC):
    """Интерфейс для воркера (потока)."""
    
    @property
    @abstractmethod
    def worker_name(self) -> str:
        """Имя воркера."""
        pass
    
    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Флаг работы воркера."""
        pass
    
    @abstractmethod
    def start(self) -> bool:
        """
        Запуск воркера.
        
        Returns:
            True если запуск успешен
        """
        pass
    
    @abstractmethod
    def stop(self) -> bool:
        """
        Остановка воркера.
        
        Returns:
            True если остановка успешна
        """
        pass

