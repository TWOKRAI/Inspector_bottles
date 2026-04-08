"""
Универсальный mixin для добавления наблюдаемости к любому менеджеру.

ObservableMixin позволяет менеджеру прозрачно взаимодействовать
с logger_manager, stats_manager, error_manager и любым пользовательским
менеджером через единый интерфейс.

## Режимы работы

1. Приватные методы (всегда доступны, pickle-совместимы):
    >>> class MyManager(BaseManager, ObservableMixin):
    ...     def __init__(self, name, logger=None):
    ...         BaseManager.__init__(self, name)
    ...         ObservableMixin.__init__(self, managers={'logger': logger})
    ...
    ...     def process(self):
    ...         self._log_info("Обработка данных")
    ...         self._record_metric("operations.count")

2. Публичные прокси-методы (auto_proxy=True, удобнее но не pickle-совместимы):
    >>> ObservableMixin.__init__(
    ...     self,
    ...     managers={'logger': logger, 'stats': stats},
    ...     auto_proxy=True   # создаст self.log_info(), self.record_metric() и т.д.
    ... )

## Гарантии pickle

Приватные методы (_log_*, _record_*, _track_*) реализованы как методы класса
и полностью совместимы с pickle (multiprocessing на Windows, spawn-режим).

Публичные прокси-методы (log_*, record_*, ...) автоматически восстанавливаются
при __setstate__, но managers после unpickle пустые — вызовы тихо возвращают None.
"""

from typing import Optional, Dict, Any, Set, List
from contextlib import contextmanager

from .core.manager_registry import ManagerRegistry
from .proxies.proxy_creator import ProxyCreator
from ..interfaces import IObservableMixin


class ObservableMixin(IObservableMixin):
    """
    Mixin для подключения любого менеджера к logger, stats, error и кастомным сервисам.

    Используйте совместно с BaseManager:

        class MyManager(BaseManager, ObservableMixin):
            def __init__(self, name, logger=None, stats=None):
                BaseManager.__init__(self, name)
                ObservableMixin.__init__(
                    self,
                    managers={'logger': logger, 'stats': stats},
                    config={'logger': True, 'stats': True},
                )

    Встроенные приватные методы (всегда доступны):
        self._log(level, message)
        self._log_debug/info/warning/error/critical(message)
        self._record_metric(name, value, tags)
        self._record_timing(name, duration, tags)
        self._track_error(error, context)

    С auto_proxy=True появляются публичные методы:
        self.log_debug/info/warning/error/critical(message)
        self.record_metric/increment/record_timing/gauge(...)
        self.track_error/record_error(...)
    """

    def __init__(
        self,
        managers: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
        auto_proxy: bool = False,
    ):
        """
        Args:
            managers:   Словарь {имя: менеджер}, например {'logger': logger_mgr}
            config:     Включение/выключение менеджеров.
                        Простая форма:  {'logger': True}
                        Подробная форма: {'logger': {'enabled': True}}
            auto_proxy: Создать публичные прокси-методы (log_info, record_metric …)
        """
        self._registry = ManagerRegistry(managers, config)
        self._auto_proxy = auto_proxy

        if auto_proxy:
            self._proxy_created = True
            self._create_proxy_methods()
        else:
            self._proxy_created = False

    # =========================================================================
    # ВСТРОЕННЫЕ МЕТОДЫ НАБЛЮДАЕМОСТИ
    # Реализованы как методы класса — полностью pickle-совместимы.
    # Если соответствующий manager не зарегистрирован или выключен — тихо
    # возвращают None, не генерируя исключений.
    # =========================================================================

    def _log(self, level: str, message: str, **kwargs) -> None:
        """Логирование через logger manager (любой уровень)."""
        self._call_manager('logger', level, message, **kwargs)

    def _log_debug(self, message: str, **kwargs) -> None:
        """Логирование уровня DEBUG через logger manager."""
        self._call_manager('logger', 'debug', message, **kwargs)

    def _log_info(self, message: str, **kwargs) -> None:
        """Логирование уровня INFO через logger manager."""
        self._call_manager('logger', 'info', message, **kwargs)

    def _log_warning(self, message: str, **kwargs) -> None:
        """Логирование уровня WARNING через logger manager."""
        self._call_manager('logger', 'warning', message, **kwargs)

    def _log_error(self, message: str, **kwargs) -> None:
        """Логирование уровня ERROR через logger manager."""
        self._call_manager('logger', 'error', message, **kwargs)

    def _log_critical(self, message: str, **kwargs) -> None:
        """Логирование уровня CRITICAL через logger manager."""
        self._call_manager('logger', 'critical', message, **kwargs)

    def _record_metric(
        self,
        metric_name: str,
        value: Any = 1,
        tags: Optional[Dict[str, str]] = None
    ) -> None:
        """Запись метрики через stats/statistics manager (stats имеет приоритет)."""
        if not self._call_manager('stats', 'record_metric', metric_name, value, tags or {}):
            self._call_manager('statistics', 'record_metric', metric_name, value, tags or {})

    def _record_timing(
        self,
        metric_name: str,
        duration: float,
        tags: Optional[Dict[str, str]] = None
    ) -> None:
        """Запись времени выполнения через stats/statistics manager."""
        if not self._call_manager('stats', 'record_timing', metric_name, duration, tags or {}):
            self._call_manager('statistics', 'record_timing', metric_name, duration, tags or {})

    def _track_error(
        self,
        error: Exception,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Отслеживание ошибки через error/errors manager."""
        ctx = context or {}
        result = self._call_manager('error', 'track_error', error, ctx)
        if result is None:
            result = self._call_manager('errors', 'track_error', error, ctx)
        if result is None:
            self._call_manager('error', 'record_error', error, ctx)

    # =========================================================================
    # ПУБЛИЧНЫЙ API — УПРАВЛЕНИЕ МЕНЕДЖЕРАМИ
    # =========================================================================

    def register_manager(self, name: str, manager: Any, enabled: bool = True) -> None:
        """
        Зарегистрировать менеджер после инициализации.

        Если auto_proxy был включён — прокси-методы будут пересозданы.

        Args:
            name:    Имя менеджера ('logger', 'stats', 'errors' и т.д.)
            manager: Экземпляр менеджера
            enabled: Включён ли сразу после регистрации
        """
        self._registry.register(name, manager, enabled)

        if getattr(self, '_proxy_created', False) or getattr(self, '_auto_proxy', False):
            self._proxy_created = True
            self._create_proxy_methods()

    def unregister_manager(self, name: str) -> None:
        """Удалить менеджер из реестра."""
        self._registry.unregister(name)

    def get_manager(self, name: str) -> Optional[Any]:
        """Получить менеджер по имени (None если не найден)."""
        return self._registry.get(name)

    def has_manager(self, name: str) -> bool:
        """Проверить наличие зарегистрированного менеджера."""
        return self._registry.has(name)

    # =========================================================================
    # ПУБЛИЧНЫЙ API — УПРАВЛЕНИЕ СОСТОЯНИЕМ
    # =========================================================================

    def enable(self, manager_name: str, enabled: bool = True) -> None:
        """Включить или выключить менеджер."""
        self._registry.enable(manager_name, enabled)

    def disable(self, manager_name: str) -> None:
        """Выключить менеджер (вызовы через _call_manager будут тихо игнорироваться)."""
        self._registry.disable(manager_name)

    def is_enabled(self, manager_name: str) -> bool:
        """True если менеджер зарегистрирован и включён."""
        return self._registry.is_enabled(manager_name)

    def get_enabled_managers(self) -> Set[str]:
        """Множество имён включённых менеджеров."""
        return self._registry.get_enabled()

    @contextmanager
    def context(self, manager_name: str, enabled: bool = True):
        """
        Контекстный менеджер для временного изменения состояния.

        Пример:
            with self.context('logger', enabled=False):
                ...  # логирование отключено
            # здесь логирование снова работает
        """
        with self._registry.context(manager_name, enabled):
            yield

    # =========================================================================
    # ПУБЛИЧНЫЙ API — КОНФИГУРАЦИЯ
    # =========================================================================

    def update_config(self, config: Dict[str, Any]) -> None:
        """Обновить конфигурацию менеджеров."""
        self._registry.update_config(config)

    def get_config(self) -> Dict[str, Any]:
        """Получить копию текущей конфигурации."""
        return self._registry.get_config()

    def get_state(self) -> Dict[str, Any]:
        """
        Снимок текущего состояния mixin.

        Returns:
            dict с ключами: config, enabled, managers, enabled_managers
        """
        return self._registry.get_state()

    # =========================================================================
    # ПУБЛИЧНЫЙ API — ДИАГНОСТИКА
    # =========================================================================

    def get_available_methods(self) -> Dict[str, List[str]]:
        """
        Список доступных методов, менеджеров и адаптеров.

        Полезно при отладке для понимания, что было создано автоматически.

        Returns:
            dict с ключами 'private', 'public', 'managers', 'adapters'
        """
        methods: Dict[str, List[str]] = {
            'private': [],
            'public': [],
            'managers': list(self._registry.managers.keys()),
            'adapters': list(getattr(self, '_adapters', {}).keys()),
        }
        for attr_name in dir(self):
            if attr_name.startswith('__'):
                continue
            if attr_name.startswith('_'):
                methods['private'].append(attr_name)
            else:
                methods['public'].append(attr_name)
        return methods

    def print_available_methods(self) -> None:
        """Вывести список доступных методов в консоль (для отладки)."""
        import json
        methods = self.get_available_methods()
        print("=" * 60)
        print("Доступные методы и менеджеры:")
        print("=" * 60)
        print(json.dumps(methods, indent=2, ensure_ascii=False))
        print("=" * 60)

    # =========================================================================
    # BACKWARD COMPAT — свойство _managers для BaseAdapter
    # =========================================================================

    @property
    def _managers(self) -> Dict[str, Any]:
        """Словарь всех зарегистрированных менеджеров (backward compat)."""
        registry = self.__dict__.get('_registry')
        return registry.managers if registry is not None else {}

    # =========================================================================
    # ВНУТРЕННИЕ МЕТОДЫ
    # =========================================================================

    def _call_manager(self, manager_name: str, method_name: str, *args, **kwargs) -> Any:
        """
        Универсальная точка вызова метода зарегистрированного менеджера.

        Безопасен при отсутствии _registry (после unpickle) — возвращает None.

        Returns:
            Результат вызова или None (если менеджер недоступен/выключен)
        """
        registry: Optional[ManagerRegistry] = self.__dict__.get('_registry')
        if registry is None or not registry.is_enabled(manager_name):
            return None

        manager = registry.get(manager_name)
        if not manager:
            return None

        try:
            method = getattr(manager, method_name, None)
            if method and callable(method):
                return method(*args, **kwargs)
        except Exception:
            pass

        return None

    def _create_proxy_methods(self) -> None:
        """Создать публичные прокси-методы (log_info, record_metric, …)."""
        ProxyCreator.create_proxy_methods(
            self,
            self._registry.managers,
            self._call_manager,
        )

    # =========================================================================
    # PICKLE SUPPORT
    # Приватные методы (_log_*, _record_*, _track_*) — методы класса, пикл-совместимы.
    # Публичные прокси-методы — замыкания в __dict__, исключаются из pickle
    # и восстанавливаются в __setstate__.
    # =========================================================================

    def __getstate__(self) -> Dict[str, Any]:
        """Pickle: исключить непикл-совместимые элементы из состояния."""
        state = self.__dict__.copy()
        _EXCLUDE = (
            # Публичные прокси-методы (замыкания)
            'log_debug', 'log_info', 'log_warning', 'log_error', 'log_critical',
            'record_metric', 'increment', 'record_timing', 'gauge',
            'track_error', 'record_error',
            # Внутренние компоненты (содержат ссылки на менеджеры)
            '_registry', '_proxy_created',
        )
        for key in _EXCLUDE:
            state.pop(key, None)
        return state

    def __setstate__(self, state: Dict[str, Any]) -> None:
        """
        Unpickle: восстановить объект.

        После восстановления:
        - _log_*/record_*/track_* работают (методы класса), но тихо возвращают None
          пока managers не будут перерегистрированы.
        - Публичные прокси-методы (log_info, …) воссоздаются если _auto_proxy=True.
        """
        self.__dict__.update(state)
        # Rebuild internal components with empty state.
        # Managers are NOT restored — they hold non-picklable resources (sockets, queues…)
        # and must be re-injected by the owner after unpickle.
        self._registry = ManagerRegistry()
        # Recreate proxy methods shell (they call _call_manager which returns None for empty registry)
        if getattr(self, '_auto_proxy', False):
            self._proxy_created = True
            self._create_proxy_methods()
        else:
            self._proxy_created = False
