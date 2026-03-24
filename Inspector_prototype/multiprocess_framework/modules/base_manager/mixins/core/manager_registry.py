"""
Реестр менеджеров для ObservableMixin.

Управление регистрацией, состоянием и конфигурацией менеджеров.
"""

from typing import Dict, Any, Optional, Set
from contextlib import contextmanager


class ManagerRegistry:
    """
    Реестр менеджеров с поддержкой состояния и конфигурации.
    
    Внутренний компонент ObservableMixin, отвечающий за:
    - Регистрацию и удаление менеджеров
    - Управление состоянием (включен/выключен)
    - Конфигурацию менеджеров
    """
    
    def __init__(self, managers: Optional[Dict[str, Any]] = None, config: Optional[Dict[str, Any]] = None):
        """
        Инициализация реестра.
        
        Args:
            managers: Словарь менеджеров {имя: менеджер}
            config: Конфигурация включения/выключения функций
        """
        self._managers: Dict[str, Any] = managers or {}
        self._config: Dict[str, Any] = config or {}
        self._enabled: Dict[str, bool] = {}
        
        # Инициализация состояния на основе конфигурации
        for manager_name, manager in self._managers.items():
            config_value = self._config.get(manager_name, True)
            if isinstance(config_value, dict):
                enabled = config_value.get('enabled', True)
            else:
                enabled = bool(config_value)
            
            self._enabled[manager_name] = (
                manager is not None and enabled
            )
    
    def register(self, name: str, manager: Any, enabled: bool = True):
        """
        Регистрация нового менеджера.
        
        Args:
            name: Имя менеджера
            manager: Экземпляр менеджера
            enabled: Включен ли по умолчанию
        """
        self._managers[name] = manager
        self._enabled[name] = enabled and manager is not None
    
    def unregister(self, name: str):
        """Удаление менеджера."""
        self._managers.pop(name, None)
        self._enabled.pop(name, None)
        self._config.pop(name, None)
    
    def get(self, name: str) -> Optional[Any]:
        """Получить менеджер по имени."""
        return self._managers.get(name)
    
    def has(self, name: str) -> bool:
        """Проверить наличие менеджера."""
        return name in self._managers and self._managers[name] is not None
    
    def enable(self, name: str, enabled: bool = True):
        """
        Включить/выключить менеджер.
        
        Args:
            name: Имя менеджера
            enabled: Включить (True) или выключить (False)
        """
        if name in self._managers:
            self._enabled[name] = enabled and self._managers[name] is not None
    
    def disable(self, name: str):
        """Выключить менеджер."""
        self.enable(name, False)
    
    def is_enabled(self, name: str) -> bool:
        """Проверить включен ли менеджер."""
        return self._enabled.get(name, False)
    
    def get_enabled(self) -> Set[str]:
        """Получить список включенных менеджеров."""
        return {name for name, enabled in self._enabled.items() if enabled}
    
    @contextmanager
    def context(self, name: str, enabled: bool = True):
        """
        Временно изменить состояние менеджера.
        
        Args:
            name: Имя менеджера
            enabled: Включить (True) или выключить (False)
        """
        old_state = self._enabled.get(name, False)
        if name in self._managers:
            self._enabled[name] = enabled and self._managers[name] is not None
        try:
            yield
        finally:
            if name in self._enabled:
                self._enabled[name] = old_state
    
    def update_config(self, config: Dict[str, Any]):
        """
        Обновление конфигурации.
        
        Args:
            config: Словарь с новыми значениями конфигурации
        """
        for key, value in config.items():
            self._config[key] = value
            
            if key in self._enabled:
                if isinstance(value, bool):
                    self._enabled[key] = value and self._managers.get(key) is not None
                elif isinstance(value, dict) and 'enabled' in value:
                    self._enabled[key] = (
                        value.get('enabled', False) and 
                        self._managers.get(key) is not None
                    )
    
    def get_config(self) -> Dict[str, Any]:
        """Получить текущую конфигурацию."""
        return self._config.copy()
    
    def get_state(self) -> Dict[str, Any]:
        """
        Получить текущее состояние.
        
        Returns:
            Словарь с информацией о состоянии
        """
        return {
            "config": self._config.copy(),
            "enabled": self._enabled.copy(),
            "managers": list(self._managers.keys()),
            "enabled_managers": list(self.get_enabled())
        }
    
    @property
    def managers(self) -> Dict[str, Any]:
        """Получить словарь всех менеджеров."""
        return self._managers





