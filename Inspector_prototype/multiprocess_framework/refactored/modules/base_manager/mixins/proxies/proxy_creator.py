"""
Создатель прокси-методов для ObservableMixin.

Автоматически создает публичные методы-прокси для стандартных менеджеров.
"""

from typing import Callable, Any, Optional, List
from ..plugins.plugin_registry import PluginRegistry


class ProxyCreator:
    """
    Создатель прокси-методов.
    
    Внутренний компонент ObservableMixin, отвечающий за:
    - Автоматическое создание публичных методов-прокси
    - Поддержку альтернативных имен менеджеров
    """
    
    @staticmethod
    def create_proxy_methods(
        instance: Any,
        managers: dict,
        call_manager_func: Callable,
        plugin_registry: Optional[PluginRegistry] = None
    ):
        """
        Создать прокси-методы на экземпляре.
        
        Args:
            instance: Экземпляр для создания методов
            managers: Словарь менеджеров
            call_manager_func: Функция для вызова менеджера
            plugin_registry: Реестр плагинов (опционально)
        """
        instance._proxy_created = True
        
        # Сначала создаем стандартные прокси-методы
        ProxyCreator._create_standard_proxies(instance, managers, call_manager_func)
        
        # Затем применяем плагины
        if plugin_registry:
            ProxyCreator._apply_plugin_proxies(instance, managers, call_manager_func, plugin_registry)
    
    @staticmethod
    def _create_standard_proxies(instance: Any, managers: dict, call_manager_func: Callable):
        """
        Создать стандартные прокси-методы.
        
        Использует встроенные плагины для создания стандартных прокси-методов.
        Это обеспечивает обратную совместимость и позволяет использовать плагины.
        """
        from ..plugins.builtin_plugins import LoggerPlugin, StatsPlugin, ErrorPlugin
        
        # Используем встроенные плагины для стандартных менеджеров
        logger_plugin = LoggerPlugin()
        stats_plugin = StatsPlugin()
        error_plugin = ErrorPlugin()
        
        logger_plugin.create_proxy_methods(instance, managers, call_manager_func)
        stats_plugin.create_proxy_methods(instance, managers, call_manager_func)
        error_plugin.create_proxy_methods(instance, managers, call_manager_func)
    
    @staticmethod
    def _apply_plugin_proxies(
        instance: Any,
        managers: dict,
        call_manager_func: Callable,
        plugin_registry: PluginRegistry
    ):
        """Применить прокси-методы из плагинов."""
        for manager_name in managers.keys():
            plugins = plugin_registry.get_plugins_for_manager(manager_name)
            for plugin in plugins:
                try:
                    plugin.create_proxy_methods(instance, managers, call_manager_func)
                except Exception:
                    # Не падаем если плагин не работает
                    pass

