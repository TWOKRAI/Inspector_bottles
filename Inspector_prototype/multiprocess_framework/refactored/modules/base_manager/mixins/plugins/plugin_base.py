"""
Базовый класс для плагинов ObservableMixin.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Callable


class ObservablePlugin(ABC):
    """
    Базовый класс для плагинов ObservableMixin.
    
    Плагины позволяют расширять функциональность миксина без изменения основного кода.
    Каждый плагин может:
    - Регистрировать кастомные методы для менеджеров
    - Создавать прокси-методы автоматически
    - Добавлять декораторы
    - Расширять функциональность
    
    Пример использования:
        class CustomLoggerPlugin(ObservablePlugin):
            def get_manager_names(self) -> list[str]:
                return ['custom_logger']
            
            def create_proxy_methods(self, instance, managers, call_manager_func):
                if 'custom_logger' in managers:
                    instance.custom_log = lambda msg: call_manager_func('custom_logger', 'log', msg)
            
            def create_private_methods(self, instance, call_manager_func):
                instance._custom_log = lambda msg: call_manager_func('custom_logger', 'log', msg)
    """
    
    @abstractmethod
    def get_manager_names(self) -> list[str]:
        """
        Получить список имен менеджеров, которые поддерживает плагин.
        
        Returns:
            Список имен менеджеров
        """
        pass
    
    def create_proxy_methods(
        self,
        instance: Any,
        managers: Dict[str, Any],
        call_manager_func: Callable
    ) -> None:
        """
        Создать публичные прокси-методы для менеджеров.
        
        Args:
            instance: Экземпляр ObservableMixin
            managers: Словарь менеджеров
            call_manager_func: Функция для вызова менеджера
        """
        pass
    
    def create_private_methods(
        self,
        instance: Any,
        call_manager_func: Callable
    ) -> None:
        """
        Создать приватные методы для менеджеров.
        
        Args:
            instance: Экземпляр ObservableMixin
            call_manager_func: Функция для вызова менеджера
        """
        pass
    
    def create_decorators(
        self,
        instance: Any,
        call_manager_func: Callable
    ) -> None:
        """
        Создать декораторы для менеджеров.
        
        Args:
            instance: Экземпляр ObservableMixin
            call_manager_func: Функция для вызова менеджера
        """
        pass
    
    def get_config_schema(self) -> Optional[Dict[str, Any]]:
        """
        Получить схему конфигурации для плагина.
        
        Returns:
            Словарь с описанием конфигурации или None
        """
        return None





