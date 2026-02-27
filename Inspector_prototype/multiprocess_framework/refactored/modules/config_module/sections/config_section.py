"""
Секция конфигурации.

Представление части конфигурации как отдельного объекта.
"""
from typing import Dict, Any, Optional
from ..core.base_config import Config


class ConfigSection:
    """
    Представление секции конфигурации.
    
    Позволяет работать с частью конфигурации как с отдельным объектом,
    при этом все изменения автоматически синхронизируются с родительским конфигом.
    
    Attributes:
        _parent: Родительский объект Config
        _key: Ключ секции
    """
    
    def __init__(self, parent_config: Config, section_key: str):
        """
        Инициализация секции конфигурации.
        
        Args:
            parent_config: Родительский объект Config
            section_key: Ключ секции (например, 'database')
        """
        self._parent = parent_config
        self._key = section_key
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Получить значение из секции.
        
        Args:
            key: Ключ внутри секции
            default: Значение по умолчанию
        
        Returns:
            Значение из секции или default
        """
        full_key = f"{self._key}.{key}" if key else self._key
        return self._parent.get(full_key, default)
    
    def set(self, key: str, value: Any) -> 'ConfigSection':
        """
        Установить значение в секции.
        
        Args:
            key: Ключ внутри секции
            value: Значение для установки
        
        Returns:
            self (для цепочки вызовов)
        """
        full_key = f"{self._key}.{key}" if key else self._key
        self._parent.set(full_key, value)
        return self
    
    def update(self, data: Dict[str, Any]) -> 'ConfigSection':
        """
        Обновить секцию из словаря.
        
        Args:
            data: Словарь с новыми значениями
        
        Returns:
            self (для цепочки вызовов)
        """
        for key, value in data.items():
            self.set(key, value)
        return self
    
    def has(self, key: str) -> bool:
        """
        Проверить наличие ключа в секции.
        
        Args:
            key: Ключ для проверки
        
        Returns:
            True если ключ существует
        """
        full_key = f"{self._key}.{key}" if key else self._key
        return self._parent.has(full_key)
    
    def remove(self, key: str) -> bool:
        """
        Удалить ключ из секции.
        
        Args:
            key: Ключ для удаления
        
        Returns:
            True если ключ был удален
        """
        full_key = f"{self._key}.{key}" if key else self._key
        return self._parent.remove(full_key)
    
    @property
    def data(self) -> Dict[str, Any]:
        """
        Получить все данные секции как словарь.
        
        Returns:
            Словарь с данными секции
        """
        return self._parent.get(self._key, {}) or {}
    
    # Магические методы для удобства
    def __getitem__(self, key: str) -> Any:
        """Поддержка синтаксиса section['key']"""
        return self.get(key)
    
    def __setitem__(self, key: str, value: Any) -> None:
        """Поддержка синтаксиса section['key'] = value"""
        self.set(key, value)
    
    def __contains__(self, key: str) -> bool:
        """Поддержка синтаксиса 'key' in section"""
        return self.has(key)
    
    def __delitem__(self, key: str) -> None:
        """Поддержка синтаксиса del section['key']"""
        if not self.remove(key):
            raise KeyError(f"ConfigSection key not found: {key}")
    
    def __repr__(self) -> str:
        """Строковое представление секции."""
        return f"ConfigSection(key='{self._key}', parent={self._parent})"

