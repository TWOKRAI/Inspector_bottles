"""
Универсальный mixin для добавления наблюдаемости и расширений.

Объединяет функциональность ObservableMixin и ManagerExtensionMixin в один
производительный и удобный инструмент для расширения менеджеров.

Философия:
- Простота: минимум кода, максимум пользы
- Производительность: кэширование методов, оптимизация вызовов
- Гибкость: автоматические прокси-методы или приватные методы
- Опциональность: работает и без менеджеров
- Расширяемость: легко добавлять новые менеджеры

Примеры использования:

1. С приватными методами (как ObservableMixin):
    >>> class MyManager(BaseManager, ObservableMixin):
    ...     def __init__(self, name, logger=None):
    ...         BaseManager.__init__(self, name)
    ...         ObservableMixin.__init__(
    ...             self,
    ...             managers={'logger': logger},
    ...             config={'logger': True}
    ...         )
    ...     def process(self):
    ...         self._log_info("Обработка данных")
    ...         return "result"

2. С автоматическими прокси-методами (как ManagerExtensionMixin):
    >>> class MyManager(BaseManager, ObservableMixin):
    ...     def __init__(self, name, logger=None, stats=None):
    ...         BaseManager.__init__(self, name)
    ...         ObservableMixin.__init__(
    ...             self,
    ...             managers={'logger': logger, 'stats': stats},
    ...             config={'logger': True, 'stats': True},
    ...             auto_proxy=True  # Автоматически создаст log_info(), record_metric() и т.д.
    ...         )
    ...     def process(self):
    ...         self.log_info("Обработка данных")  # Публичный метод
    ...         self.record_metric("operations.count")
    ...         return "result"
"""

from typing import Optional, Dict, Any, Set, List
from contextlib import contextmanager

from .core.manager_registry import ManagerRegistry
from .core.method_cache import MethodCache
from .proxies.proxy_creator import ProxyCreator
from .methods.logging_methods import LoggingMethods
from .methods.stats_methods import StatsMethods
from .methods.error_methods import ErrorMethods
from .decorators.observable_decorators import ObservableDecorators
from .plugins.plugin_registry import PluginRegistry
from .plugins.plugin_base import ObservablePlugin


class ObservableMixin:
    """
    Универсальный mixin для добавления наблюдаемости и расширений.
    
    Объединяет лучшее из ObservableMixin и ManagerExtensionMixin:
    - Поддержка приватных методов с префиксом `_` (как ObservableMixin)
    - Автоматическое создание публичных прокси-методов (как ManagerExtensionMixin)
    - Кэширование методов для производительности
    - Гибкая конфигурация
    
    Пример использования:
        class MyManager(BaseManager, ObservableMixin):
            def __init__(self, name, logger=None, stats=None):
                BaseManager.__init__(self, name)
                ObservableMixin.__init__(
                    self,
                    managers={
                        'logger': logger,
                        'stats': stats
                    },
                    config={'logger': True, 'stats': True},
                    auto_proxy=True  # Создаст log_info(), record_metric() и т.д.
                )
            
            def do_something(self):
                # Используем автоматически созданные методы
                self.log_info("Выполняю операцию")
                self.record_metric("operations.count")
                
                # Или приватные методы (всегда доступны)
                self._log_info("Тоже работает")
                self._record_metric("operations.count")
    """
    
    def __init__(
        self,
        managers: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
        auto_proxy: bool = False,
        simple_mode: bool = False,
        plugins: Optional[List[ObservablePlugin]] = None
    ):
        """
        Инициализация mixin с опциональными менеджерами.
        
        Args:
            managers: Словарь менеджеров {имя: менеджер}
            config: Конфигурация включения/выключения функций
                   Простая форма: {'logger': True}
                   Сложная форма: {'logger': {'enabled': True}}
            auto_proxy: Автоматически создавать публичные прокси-методы
                       (log_info, record_metric и т.д.)
            simple_mode: Простой режим - только приватные методы, без "магии"
                        Упрощает отладку и понимание кода
            plugins: Список плагинов для расширения функциональности
        """
        # Инициализация компонентов
        self._registry = ManagerRegistry(managers, config)
        self._cache = MethodCache()
        self._plugin_registry = PluginRegistry()
        self._simple_mode = simple_mode
        
        # Регистрация плагинов
        if plugins:
            for plugin in plugins:
                self._plugin_registry.register(plugin)
        
        # Создание специализированных методов (всегда доступны)
        LoggingMethods.create_logging_methods(self, self._call_manager)
        StatsMethods.create_stats_methods(self, self._call_manager)
        ErrorMethods.create_error_methods(self, self._call_manager)
        
        # Применение методов из плагинов
        if not simple_mode:
            self._apply_plugin_methods()
        
        # Создание декораторов (опционально, по умолчанию отключено для pickle-совместимости)
        # Декораторы создаются как локальные функции и несовместимы с pickle
        # Включите их только если объект не будет использоваться в multiprocessing
        enable_decorators = config.get('enable_decorators', False) if isinstance(config, dict) else False
        if enable_decorators and not simple_mode:
            try:
                ObservableDecorators.create_decorators(
                    self,
                    self._call_manager,
                    self._log_error,
                    self._track_error,
                    self._record_metric,
                    self._record_timing
                )
            except Exception:
                # Если не удалось создать декораторы, продолжаем без них
                pass
        
        # Применение декораторов из плагинов
        if not simple_mode:
            self._apply_plugin_decorators()
        
        # Сохраняем флаг auto_proxy для последующего использования
        self._auto_proxy = auto_proxy
        
        # Автоматическое создание прокси-методов для стандартных менеджеров
        # В simple_mode прокси-методы не создаются
        if auto_proxy and not simple_mode:
            self._proxy_created = True
            self._create_proxy_methods()
        else:
            self._proxy_created = False
    
    # ========================================================================
    # ПУБЛИЧНЫЙ API - УПРАВЛЕНИЕ МЕНЕДЖЕРАМИ
    # ========================================================================
    
    def register_manager(self, name: str, manager: Any, enabled: bool = True):
        """
        Регистрация нового менеджера.
        
        Args:
            name: Имя менеджера
            manager: Экземпляр менеджера
            enabled: Включен ли по умолчанию
        """
        self._registry.register(name, manager, enabled)
        self._cache.clear_manager(name)
        
        # Пересоздаем прокси-методы если они были созданы или если auto_proxy был включен
        if (hasattr(self, '_proxy_created') and self._proxy_created) or \
           (hasattr(self, '_auto_proxy') and self._auto_proxy):
            if not hasattr(self, '_proxy_created') or not self._proxy_created:
                self._proxy_created = True
            self._create_proxy_methods()
        
        # Применяем методы из плагинов для нового менеджера
        plugins = self._plugin_registry.get_plugins_for_manager(name)
        for plugin in plugins:
            try:
                plugin.create_private_methods(self, self._call_manager)
                if hasattr(self, '_proxy_created') and self._proxy_created:
                    plugin.create_proxy_methods(self, self._registry.managers, self._call_manager)
            except Exception:
                pass
    
    def unregister_manager(self, name: str):
        """Удаление менеджера."""
        self._registry.unregister(name)
        self._cache.clear_manager(name)
    
    def get_manager(self, name: str) -> Optional[Any]:
        """Получить менеджер по имени."""
        return self._registry.get(name)
    
    def has_manager(self, name: str) -> bool:
        """Проверить наличие менеджера."""
        return self._registry.has(name)
    
    # ========================================================================
    # ПУБЛИЧНЫЙ API - УПРАВЛЕНИЕ СОСТОЯНИЕМ
    # ========================================================================
    
    def enable(self, manager_name: str, enabled: bool = True):
        """
        Включить/выключить функцию менеджера.
        
        Args:
            manager_name: Имя менеджера
            enabled: Включить (True) или выключить (False)
        """
        self._registry.enable(manager_name, enabled)
    
    def disable(self, manager_name: str):
        """Выключить функцию менеджера."""
        self._registry.disable(manager_name)
    
    def is_enabled(self, manager_name: str) -> bool:
        """Проверить включена ли функция менеджера."""
        return self._registry.is_enabled(manager_name)
    
    def get_enabled_managers(self) -> Set[str]:
        """Получить список включенных менеджеров."""
        return self._registry.get_enabled()
    
    @contextmanager
    def context(self, manager_name: str, enabled: bool = True):
        """
        Временно изменить состояние менеджера.
        
        Args:
            manager_name: Имя менеджера
            enabled: Включить (True) или выключить (False)
        """
        with self._registry.context(manager_name, enabled):
            yield
    
    # ========================================================================
    # ВНУТРЕННИЕ МЕТОДЫ - УНИВЕРСАЛЬНЫЙ ВЫЗОВ МЕНЕДЖЕРОВ
    # ========================================================================
    
    def _call_manager(self, manager_name: str, method_name: str, *args, **kwargs) -> Any:
        """
        Универсальный метод для вызова метода менеджера.
        
        Использует кэширование методов для оптимизации производительности
        при частых вызовах одних и тех же методов.
        
        Args:
            manager_name: Имя менеджера
            method_name: Имя метода для вызова
            *args: Позиционные аргументы
            **kwargs: Именованные аргументы
            
        Returns:
            Результат вызова метода или None если менеджер не доступен
        """
        # Проверяем что _registry имеет метод is_enabled (это ManagerRegistry)
        if not hasattr(self._registry, 'is_enabled') or not self._registry.is_enabled(manager_name):
            return None
        
        manager = self._registry.get(manager_name)
        if not manager:
            return None
        
        # Проверяем кэш методов
        method = self._cache.get(manager_name, method_name)
        
        # Если метода нет в кэше, получаем его и кэшируем
        if method is None and not self._cache.has(manager_name, method_name):
            try:
                method = getattr(manager, method_name, None)
                # Кэшируем даже если метод не найден (чтобы не искать повторно)
                self._cache.set(manager_name, method_name, method if (method and callable(method)) else None)
            except Exception:
                self._cache.set(manager_name, method_name, None)
                return None
        
        # Если метод есть в кэше и он callable, вызываем его
        if method and callable(method):
            try:
                return method(*args, **kwargs)
            except Exception:
                # При ошибке вызова очищаем кэш для этого метода
                # (возможно метод был удален или изменен)
                self._cache.pop(manager_name, method_name)
                pass  # Не падаем если менеджер не работает
        
        return None
    
    # ========================================================================
    # ВНУТРЕННИЕ МЕТОДЫ - АВТОМАТИЧЕСКОЕ СОЗДАНИЕ ПРОКСИ-МЕТОДОВ
    # ========================================================================
    
    def _create_proxy_methods(self):
        """
        Создать удобные публичные методы-прокси для стандартных менеджеров.
        
        Автоматически создает методы типа log_info(), record_metric() и т.д.
        если соответствующие менеджеры зарегистрированы.
        """
        ProxyCreator.create_proxy_methods(
            self,
            self._registry.managers,
            self._call_manager,
            self._plugin_registry
        )
    
    def _apply_plugin_methods(self):
        """Применить приватные методы из плагинов."""
        for plugin in self._plugin_registry.get_all_plugins().values():
            try:
                plugin.create_private_methods(self, self._call_manager)
                # Также создаем прокси-методы если они нужны
                if hasattr(self, '_proxy_created') and self._proxy_created:
                    plugin.create_proxy_methods(self, self._registry.managers, self._call_manager)
            except Exception:
                # Не падаем если плагин не работает
                pass
    
    def _apply_plugin_decorators(self):
        """Применить декораторы из плагинов."""
        for plugin in self._plugin_registry.get_all_plugins().values():
            try:
                plugin.create_decorators(self, self._call_manager)
            except Exception:
                # Не падаем если плагин не работает
                pass
    
    # ========================================================================
    # ПУБЛИЧНЫЙ API - КОНФИГУРАЦИЯ
    # ========================================================================
    
    def update_config(self, config: Dict[str, Any]):
        """
        Обновление конфигурации.
        
        Args:
            config: Словарь с новыми значениями конфигурации
        """
        self._registry.update_config(config)
    
    def get_config(self) -> Dict[str, Any]:
        """Получить текущую конфигурацию."""
        return self._registry.get_config()
    
    def get_state(self) -> Dict[str, Any]:
        """
        Получить текущее состояние (конфигурация + включенные менеджеры).
        
        Returns:
            Словарь с информацией о состоянии:
            - config: Текущая конфигурация
            - enabled: Состояние включения менеджеров
            - managers: Список зарегистрированных менеджеров
        """
        state = self._registry.get_state()
        state['plugins'] = list(self._plugin_registry.get_all_plugins().keys())
        return state
    
    # ========================================================================
    # ПУБЛИЧНЫЙ API - УПРАВЛЕНИЕ ПЛАГИНАМИ
    # ========================================================================
    
    def register_plugin(self, plugin: ObservablePlugin, name: Optional[str] = None):
        """
        Зарегистрировать плагин для расширения функциональности.
        
        Args:
            plugin: Экземпляр плагина
            name: Имя плагина (по умолчанию имя класса)
        """
        self._plugin_registry.register(plugin, name)
        
        # Применяем методы плагина
        try:
            plugin.create_private_methods(self, self._call_manager)
            # Создаем прокси-методы если auto_proxy включен
            if hasattr(self, '_proxy_created') and self._proxy_created:
                plugin.create_proxy_methods(self, self._registry.managers, self._call_manager)
            plugin.create_decorators(self, self._call_manager)
        except Exception:
            pass
        
        # Если auto_proxy включен, пересоздаем прокси-методы для применения нового плагина
        if hasattr(self, '_proxy_created') and self._proxy_created:
            self._create_proxy_methods()
    
    def unregister_plugin(self, name: str):
        """Удалить плагин из реестра."""
        self._plugin_registry.unregister(name)
    
    def has_plugin(self, name: str) -> bool:
        """Проверить наличие плагина."""
        return self._plugin_registry.has_plugin(name)
    
    def get_plugin(self, name: str) -> Optional[ObservablePlugin]:
        """Получить плагин по имени."""
        return self._plugin_registry.get_all_plugins().get(name)
    
    # ========================================================================
    # ПУБЛИЧНЫЙ API - ДИАГНОСТИКА И ОТЛАДКА
    # ========================================================================
    
    def get_available_methods(self) -> Dict[str, List[str]]:
        """
        Получить список доступных методов для отладки.
        
        Полезно для понимания какие методы были созданы автоматически
        и какие менеджеры доступны.
        
        Returns:
            Словарь с категориями методов:
            - 'private': Приватные методы (начинаются с _)
            - 'public': Публичные методы (не начинаются с _)
            - 'managers': Доступные менеджеры
            - 'adapters': Доступные адаптеры (если есть BaseManager)
        """
        methods = {
            'private': [],
            'public': [],
            'managers': list(self._registry.managers.keys()) if hasattr(self._registry, 'managers') else [],
            'adapters': []
        }
        
        # Получаем все методы объекта
        for attr_name in dir(self):
            if attr_name.startswith('__'):
                continue
            
            if attr_name.startswith('_'):
                methods['private'].append(attr_name)
            else:
                methods['public'].append(attr_name)
        
        # Если это BaseManager, добавляем информацию об адаптерах
        if hasattr(self, '_adapters'):
            methods['adapters'] = list(self._adapters.keys())
        
        return methods
    
    def print_available_methods(self):
        """Вывести список доступных методов для отладки."""
        import json
        methods = self.get_available_methods()
        print("=" * 60)
        print("Доступные методы и менеджеры:")
        print("=" * 60)
        print(json.dumps(methods, indent=2, ensure_ascii=False))
        print("=" * 60)
