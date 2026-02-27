"""
Универсальный mixin для добавления наблюдаемости (логирование, ошибки, статистика и др.).

Простой адаптер для связи классов с менеджерами без усложнения основного функционала.
Предоставляет легкий способ интеграции любых менеджеров через единый интерфейс.

Философия:
- Простота: минимум кода, максимум пользы
- Без блокировок: не нужны для однопоточного использования
- Опциональность: работает и без менеджеров
- Расширяемость: легко добавлять новые менеджеры

Полная документация доступна в README.md модуля Base_manager_module.

Примеры использования:
    >>> class MyService(ObservableMixin):
    ...     def __init__(self, logger=None):
    ...         managers = {}
    ...         if logger:
    ...             managers['logger'] = logger
    ...         ObservableMixin.__init__(self, managers=managers, config={'logger': True})
    ...
    ...     def process(self):
    ...         self._log_info("Обработка данных")
    ...         return "result"
"""
from typing import Optional, Dict, Any, Callable, Set
from functools import wraps
from contextlib import contextmanager


class ObservableMixin:
    """
    Универсальный mixin для добавления наблюдаемости.
    
    Простой адаптер для связи классов с менеджерами (логирование, ошибки, статистика и т.п.).
    Не усложняет код, а упрощает интеграцию с различными менеджерами.
    
    Пример использования:
        class MyManager(ObservableMixin):
            def __init__(self):
                ObservableMixin.__init__(
                    self,
                    managers={
                        'logger': logger_manager,
                        'stats': stats_manager
                    },
                    config={'logger': True, 'stats': True}
                )
            
            def do_something(self):
                self._log_info("Выполняю операцию")
                try:
                    result = self.process()
                    self._record_metric("operations.success")
                    return result
                except Exception as e:
                    self._track_error(e)
                    raise
    """
    
    def __init__(
        self,
        managers: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Инициализация mixin с опциональными менеджерами.
        
        Args:
            managers: Словарь менеджеров {имя: менеджер}
            config: Конфигурация включения/выключения функций {имя: bool}
        """
        self._managers: Dict[str, Any] = managers or {}
        self._config: Dict[str, bool] = config or {}
        
        # Состояние включения/выключения менеджеров
        # По умолчанию менеджер включен, если он есть и в конфиге разрешено (или по умолчанию True)
        self._enabled: Dict[str, bool] = {}
        for manager_name, manager in self._managers.items():
            self._enabled[manager_name] = (
                manager is not None and 
                self._config.get(manager_name, True)
            )
        
        # Кэш для методов менеджеров (оптимизация производительности)
        # Формат: {(manager_name, method_name): callable_method}
        self._method_cache: Dict[tuple[str, str], Optional[Callable]] = {}
    
    def register_manager(self, name: str, manager: Any, enabled: bool = True):
        """
        Регистрация нового менеджера.
        
        Args:
            name: Имя менеджера
            manager: Экземпляр менеджера
            enabled: Включен ли по умолчанию
        """
        self._managers[name] = manager
        self._enabled[name] = enabled and manager is not None
        # Очищаем кэш методов для этого менеджера
        self._method_cache = {k: v for k, v in self._method_cache.items() if k[0] != name}
    
    def unregister_manager(self, name: str):
        """Удаление менеджера."""
        self._managers.pop(name, None)
        self._enabled.pop(name, None)
        # Очищаем кэш методов для этого менеджера
        self._method_cache = {k: v for k, v in self._method_cache.items() if k[0] != name}
    
    def get_manager(self, name: str) -> Optional[Any]:
        """Получить менеджер по имени."""
        return self._managers.get(name)
    
    def has_manager(self, name: str) -> bool:
        """Проверить наличие менеджера."""
        return name in self._managers and self._managers[name] is not None
    
    # Методы для управления состоянием
    
    def enable(self, manager_name: str, enabled: bool = True):
        """
        Включить/выключить функцию менеджера.
        
        Args:
            manager_name: Имя менеджера
            enabled: Включить (True) или выключить (False)
        """
        if manager_name in self._managers:
            self._enabled[manager_name] = enabled and self._managers[manager_name] is not None
            # Очищаем кэш методов при изменении состояния (на всякий случай)
            # В реальности кэш не зависит от enabled, но для безопасности очищаем
            if not enabled:
                self._method_cache = {k: v for k, v in self._method_cache.items() if k[0] != manager_name}
    
    def disable(self, manager_name: str):
        """Выключить функцию менеджера."""
        self.enable(manager_name, False)
    
    def is_enabled(self, manager_name: str) -> bool:
        """Проверить включена ли функция менеджера."""
        return self._enabled.get(manager_name, False)
    
    def get_enabled_managers(self) -> Set[str]:
        """Получить список включенных менеджеров."""
        return {name for name, enabled in self._enabled.items() if enabled}
    
    # Контекстные менеджеры для временного управления
    
    @contextmanager
    def context(self, manager_name: str, enabled: bool = True):
        """
        Временно изменить состояние менеджера.
        
        Args:
            manager_name: Имя менеджера
            enabled: Включить (True) или выключить (False)
        """
        old_state = self._enabled.get(manager_name, False)
        if manager_name in self._managers:
            self._enabled[manager_name] = enabled and self._managers[manager_name] is not None
        try:
            yield
        finally:
            if manager_name in self._enabled:
                self._enabled[manager_name] = old_state
    
    # Универсальный метод для вызова менеджеров
    
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
        if not self.is_enabled(manager_name):
            return None
        
        manager = self._managers.get(manager_name)
        if not manager:
            return None
        
        # Проверяем кэш методов
        cache_key = (manager_name, method_name)
        method = self._method_cache.get(cache_key)
        
        # Если метода нет в кэше, получаем его и кэшируем
        if method is None and cache_key not in self._method_cache:
            try:
                method = getattr(manager, method_name, None)
                # Кэшируем даже если метод не найден (чтобы не искать повторно)
                self._method_cache[cache_key] = method if (method and callable(method)) else None
            except Exception:
                self._method_cache[cache_key] = None
                return None
        
        # Если метод есть в кэше и он callable, вызываем его
        if method and callable(method):
            try:
                return method(*args, **kwargs)
            except Exception:
                # При ошибке вызова очищаем кэш для этого метода
                # (возможно метод был удален или изменен)
                self._method_cache.pop(cache_key, None)
                pass  # Не падаем если менеджер не работает
        
        return None
    
    # Специализированные методы для стандартных менеджеров
    
    def _log(self, level: str, message: str, **kwargs):
        """Логирование через logger_manager."""
        self._call_manager('logger', level, message, **kwargs)
    
    def _log_debug(self, message: str, **kwargs):
        """Логирование отладочной информации."""
        self._log("debug", message, **kwargs)
    
    def _log_info(self, message: str, **kwargs):
        """Логирование информационного сообщения."""
        self._log("info", message, **kwargs)
    
    def _log_warning(self, message: str, **kwargs):
        """Логирование предупреждения."""
        self._log("warning", message, **kwargs)
    
    def _log_error(self, message: str, **kwargs):
        """Логирование ошибки."""
        self._log("error", message, **kwargs)
    
    def _track_error(self, error: Exception, context: Dict[str, Any] = None):
        """Отслеживание ошибки через error_manager."""
        if not self._call_manager('error', 'track_error', error, context or {}):
            # Fallback на record_error
            self._call_manager('error', 'record_error', error, context or {})
    
    def _record_metric(self, metric_name: str, value: Any = 1, tags: Dict[str, str] = None):
        """Запись метрики через statistics_manager."""
        if not self._call_manager('statistics', 'record_metric', metric_name, value, tags or {}):
            # Fallback на increment
            self._call_manager('statistics', 'increment', metric_name, tags or {})
    
    def _record_timing(self, metric_name: str, duration: float, tags: Dict[str, str] = None):
        """Запись времени выполнения через statistics_manager."""
        if not self._call_manager('statistics', 'record_timing', metric_name, duration, tags or {}):
            # Fallback на timing
            self._call_manager('statistics', 'timing', metric_name, duration, tags or {})
    
    # Декораторы для автоматического логирования
    
    def logged(self, manager_name: str = 'logger', level: str = "info", log_args: bool = False, log_result: bool = False):
        """
        Декоратор для автоматического логирования вызовов методов.
        
        Args:
            manager_name: Имя менеджера для логирования (по умолчанию 'logger')
            level: Уровень логирования (debug, info, warning, error)
            log_args: Логировать аргументы метода
            log_result: Логировать результат выполнения
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs):
                method_name = f"{func.__module__}.{func.__qualname__}"
                
                # Логирование начала выполнения
                if log_args:
                    self._call_manager(manager_name, level, f"Calling {method_name}", args=args, kwargs=kwargs)
                else:
                    self._call_manager(manager_name, level, f"Calling {method_name}")
                
                try:
                    result = func(*args, **kwargs)
                    
                    # Логирование результата
                    if log_result:
                        self._call_manager(manager_name, level, f"{method_name} completed", result=result)
                    
                    return result
                except Exception as e:
                    self._log_error(f"{method_name} failed: {str(e)}")
                    self._track_error(e, {"method": method_name, "args": str(args), "kwargs": str(kwargs)})
                    raise
            
            return wrapper
        return decorator
    
    def timed(self, manager_name: str = 'statistics', metric_name: str = None, tags: Dict[str, str] = None):
        """
        Декоратор для автоматического измерения времени выполнения.
        
        Args:
            manager_name: Имя менеджера статистики (по умолчанию 'statistics')
            metric_name: Имя метрики (по умолчанию используется имя метода)
            tags: Теги для метрики
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs):
                import time
                
                metric = metric_name or f"{func.__module__}.{func.__qualname__}"
                start_time = time.time()
                
                try:
                    result = func(*args, **kwargs)
                    duration = time.time() - start_time
                    self._record_timing(metric, duration, tags)
                    return result
                except Exception as e:
                    duration = time.time() - start_time
                    self._record_timing(f"{metric}.error", duration, tags)
                    raise
            
            return wrapper
        return decorator
    
    def monitored(self, manager_name: str = 'logger', level: str = "info", metric_name: str = None):
        """
        Комбинированный декоратор для логирования и статистики.
        
        Args:
            manager_name: Имя менеджера для логирования
            level: Уровень логирования
            metric_name: Имя метрики для статистики
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs):
                import time
                
                method_name = f"{func.__module__}.{func.__qualname__}"
                metric = metric_name or method_name
                start_time = time.time()
                
                # Логирование начала
                self._call_manager(manager_name, level, f"Executing {method_name}")
                self._record_metric(f"{metric}.calls")
                
                try:
                    result = func(*args, **kwargs)
                    duration = time.time() - start_time
                    
                    # Логирование успеха
                    self._call_manager(manager_name, level, f"{method_name} completed in {duration:.3f}s")
                    self._record_timing(f"{metric}.duration", duration)
                    self._record_metric(f"{metric}.success")
                    
                    return result
                except Exception as e:
                    duration = time.time() - start_time
                    
                    # Логирование ошибки
                    self._log_error(f"{method_name} failed: {str(e)}")
                    self._track_error(e, {"method": method_name})
                    self._record_timing(f"{metric}.error_duration", duration)
                    self._record_metric(f"{metric}.errors")
                    
                    raise
            
            return wrapper
        return decorator
    
    # Методы для работы с конфигурацией
    
    def update_config(self, config: Dict[str, Any]):
        """
        Обновление конфигурации.
        
        Args:
            config: Словарь с новыми значениями конфигурации
        """
        for key, value in config.items():
            # Обновляем конфигурацию
            self._config[key] = value
            
            # Обновляем состояние менеджера если это булево значение
            if key in self._enabled:
                if isinstance(value, bool):
                    self._enabled[key] = value and self._managers.get(key) is not None
                elif isinstance(value, dict) and 'enabled' in value:
                    # Поддержка сложных конфигов с полем enabled
                    self._enabled[key] = (
                        value.get('enabled', False) and 
                        self._managers.get(key) is not None
                    )
    
    def get_config(self) -> Dict[str, Any]:
        """Получить текущую конфигурацию."""
        return self._config.copy()
    
    def get_state(self) -> Dict[str, Any]:
        """
        Получить текущее состояние (конфигурация + включенные менеджеры).
        
        Returns:
            Словарь с информацией о состоянии:
            - config: Текущая конфигурация
            - enabled: Состояние включения менеджеров
            - managers: Список зарегистрированных менеджеров
        """
        return {
            "config": self._config.copy(),
            "enabled": self._enabled.copy(),
            "managers": list(self._managers.keys()),
            "enabled_managers": list(self.get_enabled_managers())
        }
