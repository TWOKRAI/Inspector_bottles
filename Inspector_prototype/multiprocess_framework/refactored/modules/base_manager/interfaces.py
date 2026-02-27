"""
Интерфейсы для Base Manager Module.

Интерфейсы определяют контракты для классов модуля и используются для:
- Документации ожидаемого поведения
- Проверки соответствия в тестах
- Type hints для статической проверки типов
- Создания моков для тестирования

Для использования в type hints используйте TYPE_CHECKING:
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from .interfaces import IBaseManager
"""

from abc import ABC, abstractmethod
from typing import Any, Optional, Dict, Set
from contextlib import contextmanager

# Импорт для ObservableMixin интерфейса (избегаем циклических импортов)
try:
    from .mixins.plugins.plugin_base import ObservablePlugin
except ImportError:
    ObservablePlugin = Any  # Fallback для случаев когда плагины не доступны


class IBaseManager(ABC):
    """
    Интерфейс базового менеджера.
    
    Все менеджеры системы должны реализовывать этот интерфейс.
    Используется для проверки соответствия контракту в тестах и type hints.
    """
    
    @abstractmethod
    def initialize(self) -> bool:
        """
        Инициализация менеджера.
        
        Returns:
            bool: True если инициализация успешна
        """
        pass
    
    @abstractmethod
    def shutdown(self) -> bool:
        """
        Корректное завершение работы менеджера.
        
        Returns:
            bool: True если завершение успешно
        """
        pass
    
    @abstractmethod
    def attach_adapter(self, adapter: Any, name: Optional[str] = None) -> bool:
        """
        Подключить адаптер к менеджеру.
        
        Args:
            adapter: Экземпляр адаптера
            name: Имя адаптера (опционально)
            
        Returns:
            bool: True если адаптер успешно подключен
        """
        pass
    
    @abstractmethod
    def get_adapter(self, name: Optional[str] = None) -> Optional[Any]:
        """
        Получить адаптер по имени.
        
        Args:
            name: Имя адаптера
            
        Returns:
            Адаптер или None если не найден
        """
        pass


class IBaseAdapter(ABC):
    """
    Интерфейс базового адаптера.
    
    Все адаптеры менеджеров должны реализовывать этот интерфейс.
    Используется для проверки соответствия контракту в тестах и type hints.
    """
    
    @abstractmethod
    def setup(self) -> bool:
        """
        Настройка адаптера и интеграция с менеджером.
        
        Returns:
            bool: True если настройка успешна
        """
        pass
    
    @abstractmethod
    def is_initialized(self) -> bool:
        """
        Проверка инициализации адаптера.
        
        Returns:
            bool: True если адаптер инициализирован
        """
        pass


class IObservableMixin(ABC):
    """
    Интерфейс для ObservableMixin.
    
    Определяет контракт для ObservableMixin - универсального миксина
    для добавления наблюдаемости и расширений к менеджерам.
    
    Примечание: Полный интерфейс находится в mixins/interfaces.py
    для избежания циклических импортов. Этот интерфейс - базовая версия.
    """
    
    @abstractmethod
    def register_manager(self, name: str, manager: Any, enabled: bool = True):
        """Регистрация нового менеджера."""
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
        """Включить/выключить функцию менеджера."""
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
    def get_config(self) -> Dict[str, Any]:
        """Получить текущую конфигурацию."""
        pass
    
    @abstractmethod
    def get_state(self) -> Dict[str, Any]:
        """Получить текущее состояние."""
        pass

