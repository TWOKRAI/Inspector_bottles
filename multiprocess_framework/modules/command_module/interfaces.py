"""
Интерфейсы для CommandModule.

Определяют контракты для командных менеджеров и адаптеров.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Callable, List, Optional

from ..base_manager.interfaces import IBaseManager


class ICommandManager(IBaseManager, ABC):
    """
    Интерфейс для командных менеджеров.
    
    Определяет контракт для регистрации и выполнения команд.
    """
    
    @abstractmethod
    def register_command(
        self,
        command_name: str,
        handler: Callable,
        expects_full_message: bool = False,
        metadata: Dict[str, Any] = None,
        efficiency: int = 0,
        tags: List[str] = None,
        strategy: Optional[Any] = None,
        **kwargs
    ) -> bool:
        """
        Регистрация новой команды.
        
        Args:
            command_name: Название команды
            handler: Функция-обработчик команды
            expects_full_message: Если True, обработчик получает всё сообщение
            metadata: Дополнительные метаданные команды
            efficiency: Уровень эффективности
            tags: Список тегов для группировки
            strategy: Стратегия для регистрации
            **kwargs: Дополнительные аргументы
            
        Returns:
            bool: Успешность регистрации
        """
        pass
    
    @abstractmethod
    def handle_command(self, message: Dict) -> Any:
        """
        Обработка командного сообщения.
        
        Args:
            message: Сообщение для обработки
            
        Returns:
            Результат выполнения команды или сообщение об ошибке
        """
        pass
    
    @abstractmethod
    def get_commands(self) -> List[Dict]:
        """
        Получение списка всех зарегистрированных команд.
        
        Returns:
            Список словарей с информацией о командах
        """
        pass
    
    @abstractmethod
    def get_command_info(self, command_name: str) -> Optional[Dict]:
        """
        Получение информации о конкретной команде.
        
        Args:
            command_name: Название команды
            
        Returns:
            Словарь с информацией о команде или None
        """
        pass
    
    @abstractmethod
    def get_commands_by_tag(self, tag: str) -> List[Dict]:
        """
        Получение команд по тегу.
        
        Args:
            tag: Тег для фильтрации
            
        Returns:
            Список команд с указанным тегом
        """
        pass
    
    @abstractmethod
    def update_command_metadata(self, command_name: str, metadata: Dict[str, Any]) -> bool:
        """
        Обновление метаданных команды.
        
        Args:
            command_name: Название команды
            metadata: Новые метаданные
            
        Returns:
            True если обновлено, False в случае ошибки
        """
        pass
    
    @abstractmethod
    def update_command_tags(self, command_name: str, tags: List[str]) -> bool:
        """
        Обновление тегов команды.
        
        Args:
            command_name: Название команды
            tags: Новые теги
            
        Returns:
            True если обновлено, False в случае ошибки
        """
        pass
    
    @abstractmethod
    def overwrite_command(
        self,
        command_name: str,
        handler: Callable,
        expects_full_message: bool = False,
        metadata: Dict[str, Any] = None,
        efficiency: int = 0,
        tags: List[str] = None
    ) -> bool:
        """
        Принудительная перезапись команды.
        
        Args:
            command_name: Название команды
            handler: Новый обработчик
            expects_full_message: Если True, обработчик получает всё сообщение
            metadata: Метаданные команды
            efficiency: Уровень эффективности
            tags: Список тегов
            
        Returns:
            True если перезаписано, False в случае ошибки
        """
        pass

