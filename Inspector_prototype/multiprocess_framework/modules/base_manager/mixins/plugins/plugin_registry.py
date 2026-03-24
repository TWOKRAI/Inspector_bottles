"""
Реестр плагинов для ObservableMixin.
"""

from typing import Dict, List, Type, Optional
from .plugin_base import ObservablePlugin


class PluginRegistry:
    """
    Реестр плагинов для ObservableMixin.
    
    Управляет регистрацией и использованием плагинов для расширения функциональности.
    """
    
    def __init__(self):
        """Инициализация реестра."""
        self._plugins: Dict[str, ObservablePlugin] = {}
        self._manager_to_plugins: Dict[str, List[str]] = {}
    
    def register(self, plugin: ObservablePlugin, name: Optional[str] = None):
        """
        Зарегистрировать плагин.
        
        Args:
            plugin: Экземпляр плагина
            name: Имя плагина (по умолчанию имя класса)
        """
        if name is None:
            name = plugin.__class__.__name__
        
        self._plugins[name] = plugin
        
        # Индексируем менеджеры плагина
        for manager_name in plugin.get_manager_names():
            if manager_name not in self._manager_to_plugins:
                self._manager_to_plugins[manager_name] = []
            self._manager_to_plugins[manager_name].append(name)
    
    def unregister(self, name: str):
        """Удалить плагин из реестра."""
        if name not in self._plugins:
            return
        
        plugin = self._plugins[name]
        
        # Удаляем индексацию
        for manager_name in plugin.get_manager_names():
            if manager_name in self._manager_to_plugins:
                self._manager_to_plugins[manager_name].remove(name)
                if not self._manager_to_plugins[manager_name]:
                    del self._manager_to_plugins[manager_name]
        
        del self._plugins[name]
    
    def get_plugins_for_manager(self, manager_name: str) -> List[ObservablePlugin]:
        """
        Получить плагины для конкретного менеджера.
        
        Args:
            manager_name: Имя менеджера
            
        Returns:
            Список плагинов для менеджера
        """
        plugin_names = self._manager_to_plugins.get(manager_name, [])
        return [self._plugins[name] for name in plugin_names if name in self._plugins]
    
    def get_all_plugins(self) -> Dict[str, ObservablePlugin]:
        """Получить все зарегистрированные плагины."""
        return self._plugins.copy()
    
    def has_plugin(self, name: str) -> bool:
        """Проверить наличие плагина."""
        return name in self._plugins
    
    def clear(self):
        """Очистить реестр плагинов."""
        self._plugins.clear()
        self._manager_to_plugins.clear()





