"""
Интерфейсы для ObservableMixin.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional, Dict, Set
from contextlib import contextmanager

from .plugins.plugin_base import ObservablePlugin


class IObservableMixin(ABC):
    """Интерфейс для ObservableMixin."""
    
    @abstractmethod
    def register_manager(self, name: str, manager: Any, enabled: bool = True):
        """
        Регистрация нового менеджера.
        
        Args:
            name: Имя менеджера
            manager: Экземпляр менеджера
            enabled: Включен ли по умолчанию
        """
        pass
    
    @abstractmethod
    def unregister_manager(self, name: str):
        """Удаление менеджера."""
        pass
    
    @abstractmethod
    def get_manager(self, name: str) -> Optional[Any]:
        """Получить менеджер по имени."""
        pass
    
    @abstractmethod
    def has_manager(self, name: str) -> bool:
        """Проверить наличие менеджера."""
        pass
    
    @abstractmethod
    def enable(self, manager_name: str, enabled: bool = True):
        """
        Включить/выключить функцию менеджера.
        
        Args:
            manager_name: Имя менеджера
            enabled: Включить (True) или выключить (False)
        """
        pass
    
    @abstractmethod
    def disable(self, manager_name: str):
        """Выключить функцию менеджера."""
        pass
    
    @abstractmethod
    def is_enabled(self, manager_name: str) -> bool:
        """Проверить включена ли функция менеджера."""
        pass
    
    @abstractmethod
    def get_enabled_managers(self) -> Set[str]:
        """Получить список включенных менеджеров."""
        pass
    
    @abstractmethod
    def context(self, manager_name: str, enabled: bool = True):
        """
        Временно изменить состояние менеджера.
        
        Args:
            manager_name: Имя менеджера
            enabled: Включить (True) или выключить (False)
        """
        pass
    
    @abstractmethod
    def update_config(self, config: Dict[str, Any]):
        """
        Обновление конфигурации.
        
        Args:
            config: Словарь с новыми значениями конфигурации
        """
        pass
    
    @abstractmethod
    def get_config(self) -> Dict[str, Any]:
        """Получить текущую конфигурацию."""
        pass
    
    @abstractmethod
    def get_state(self) -> Dict[str, Any]:
        """
        Получить текущее состояние.
        
        Returns:
            Словарь с информацией о состоянии
        """
        pass

