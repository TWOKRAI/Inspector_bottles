"""
Интерфейсы для ConfigModule.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Union, Callable
from pathlib import Path

from ..base_manager.interfaces import IBaseManager


class IConfig(ABC):
    """
    Интерфейс для работы с конфигурацией.
    """
    
    @abstractmethod
    def get(self, key: str, default: Any = None, env_fallback: bool = True) -> Any:
        """Получить значение по ключу."""
        pass
    
    @abstractmethod
    def set(self, key: str, value: Any, notify: bool = True) -> 'IConfig':
        """Установить значение по ключу."""
        pass
    
    @abstractmethod
    def has(self, key: str) -> bool:
        """Проверить наличие ключа."""
        pass
    
    @abstractmethod
    def remove(self, key: str) -> bool:
        """Удалить ключ."""
        pass
    
    @abstractmethod
    def load(self, file_path: Union[str, Path], merge: bool = True) -> 'IConfig':
        """Загрузить конфигурацию из файла."""
        pass
    
    @abstractmethod
    def save(self, file_path: Optional[Union[str, Path]] = None) -> 'IConfig':
        """Сохранить конфигурацию в файл."""
        pass
    
    @property
    @abstractmethod
    def data(self) -> Dict[str, Any]:
        """Получить все данные конфигурации."""
        pass


class IConfigManager(IBaseManager, ABC):
    """
    Интерфейс для менеджера конфигураций.
    """
    
    @abstractmethod
    def get_config(self, name: str) -> Optional[IConfig]:
        """Получить конфигурацию по имени."""
        pass
    
    @abstractmethod
    def create_config(
        self,
        name: str,
        initial_data: Optional[Dict[str, Any]] = None,
        file_path: Optional[Union[str, Path]] = None,
        validation_schema: Optional[Any] = None
    ) -> IConfig:
        """Создать новую конфигурацию."""
        pass
    
    @abstractmethod
    def remove_config(self, name: str) -> bool:
        """Удалить конфигурацию."""
        pass
    
    @abstractmethod
    def list_configs(self) -> list[str]:
        """Получить список всех конфигураций."""
        pass
    
    @abstractmethod
    def sync_config(self, name: str, process_name: Optional[str] = None) -> bool:
        """Синхронизировать конфигурацию с ProcessData (ручная синхронизация)."""
        pass
    
    @abstractmethod
    def load_config_from_storage(self, name: str, process_name: Optional[str] = None) -> bool:
        """Загрузить конфигурацию из ProcessData."""
        pass

