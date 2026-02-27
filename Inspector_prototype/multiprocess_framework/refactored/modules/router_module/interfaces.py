"""
Интерфейсы для RouterModule.

Определяет контракты для компонентов модуля маршрутизации сообщений.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Callable, Union

# Импорт для типизации
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ...message_module import Message


class IRouterManager(ABC):
    """
    Интерфейс для менеджера маршрутизации сообщений.
    
    Определяет контракт для всех реализаций роутера.
    """
    
    @property
    @abstractmethod
    def manager_name(self) -> str:
        """Имя роутера."""
        pass
    
    @abstractmethod
    def initialize(self) -> bool:
        """
        Инициализация роутера.
        
        Returns:
            bool: True если инициализация успешна
        """
        pass
    
    @abstractmethod
    def shutdown(self) -> bool:
        """
        Завершение работы роутера.
        
        Returns:
            bool: True если завершение успешно
        """
        pass
    
    @abstractmethod
    def send(self, message: Union['Message', Dict[str, Any]]) -> Dict[str, Any]:
        """
        Отправить сообщение с интеллектуальным выбором канала.
        
        Args:
            message: Сообщение для отправки (Message объект или словарь)
            
        Returns:
            Результат отправки
        """
        pass
    
    @abstractmethod
    def receive(self, timeout: float = 0.0, return_messages: bool = True) -> List[Union['Message', Dict[str, Any]]]:
        """
        Получить сообщения со всех каналов.
        
        Args:
            timeout: Таймаут опроса
            return_messages: Если True, возвращает Message объекты, иначе словари
            
        Returns:
            Список сообщений
        """
        pass
    
    @abstractmethod
    def register_channel(self, channel: 'IMessageChannel') -> bool:
        """
        Зарегистрировать канал в роутере.
        
        Args:
            channel: Канал, реализующий интерфейс IMessageChannel
            
        Returns:
            True если канал успешно зарегистрирован
        """
        pass
    
    @abstractmethod
    def unregister_channel(self, channel_name: str) -> bool:
        """
        Удалить канал из роутера.
        
        Args:
            channel_name: Имя канала для удаления
            
        Returns:
            True если канал успешно удален
        """
        pass
    
    @abstractmethod
    def get_channel(self, channel_name: str) -> Optional['IMessageChannel']:
        """
        Получить канал по имени.
        
        Args:
            channel_name: Имя канала
            
        Returns:
            Канал или None если не найден
        """
        pass
    
    @abstractmethod
    def register_channel_handler(
        self,
        key: str,
        handler: Callable,
        expects_full_message: bool = True,
        metadata: Dict[str, Any] = None,
        efficiency: int = 0,
        tags: List[str] = None
    ) -> bool:
        """
        Зарегистрировать кастомный обработчик для выбора каналов.
        
        Args:
            key: Ключ для диспетчеризации
            handler: Функция-обработчик, возвращающая channel_name
            expects_full_message: Использовать полное сообщение
            metadata: Метаданные обработчика
            efficiency: Уровень эффективности обработчика
            tags: Теги для группировки
            
        Returns:
            True если регистрация успешна
        """
        pass
    
    @abstractmethod
    def register_message_handler(
        self,
        key: str,
        handler: Callable,
        expects_full_message: bool = True,
        metadata: Dict[str, Any] = None,
        efficiency: int = 0,
        tags: List[str] = None
    ) -> bool:
        """
        Зарегистрировать обработчик для входящих сообщений.
        
        Args:
            key: Ключ для диспетчеризации входящих сообщений
            handler: Функция-обработчик входящих сообщений
            expects_full_message: Использовать полное сообщение
            metadata: Метаданные обработчика
            efficiency: Уровень эффективности обработчика
            tags: Теги для группировки
            
        Returns:
            True если регистрация успешна
        """
        pass
    
    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """
        Получить статистику работы роутера.
        
        Returns:
            Словарь со статистикой
        """
        pass


class IMessageChannel(ABC):
    """
    Интерфейс для каналов сообщений.
    
    Определяет контракт для всех типов каналов (Queue, Logger, HTTP, etc.).
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Уникальное имя канала."""
        pass
    
    @property
    @abstractmethod
    def channel_type(self) -> str:
        """Тип канала (queue, log, telegram, http, etc)."""
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
    
    def start_listening(self, callback: Callable[[Dict[str, Any]], None]) -> bool:
        """
        Запуск асинхронного прослушивания канала.
        
        Args:
            callback: Функция обратного вызова для полученных сообщений
            
        Returns:
            True если запущено успешно
        """
        return False
    
    def stop_listening(self) -> bool:
        """Остановить прослушивание канала."""
        return True
    
    def get_info(self) -> Dict[str, Any]:
        """
        Получить информацию о канале.
        
        Returns:
            Словарь с информацией о канале
        """
        return {
            "name": self.name,
            "type": self.channel_type,
            "active": True
        }

