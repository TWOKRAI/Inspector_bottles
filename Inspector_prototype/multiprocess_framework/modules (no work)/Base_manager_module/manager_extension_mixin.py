"""
Универсальный mixin для расширения менеджеров.

Позволяет легко добавлять функциональность других менеджеров к любому менеджеру
без нарушения его основной логики. Использует паттерн Composition + Strategy.

Философия:
- Не нарушаем логику класса - только дополняем
- Легко добавлять новые расширения
- Опциональность - работает и без расширений
- Единый интерфейс для всех менеджеров

Примеры использования:
    >>> class MyManager(BaseManager, ManagerExtensionMixin):
    ...     def __init__(self, name):
    ...         BaseManager.__init__(self, name)
    ...         ManagerExtensionMixin.__init__(
    ...             self,
    ...             extensions={
    ...                 'logger': logger_manager,
    ...                 'stats': stats_manager,
    ...                 'errors': error_manager
    ...             }
    ...         )
    ...
    ...     def process(self):
    ...         self.log_info("Обработка данных")
    ...         self.record_metric("operations.count")
    ...         return "result"
"""

from typing import Optional, Dict, Any, Callable, Set, List
from functools import wraps
from contextlib import contextmanager


class ManagerExtensionMixin:
    """
    Универсальный mixin для расширения менеджеров.
    
    Позволяет легко добавлять функциональность других менеджеров (логирование,
    статистика, ошибки и т.д.) к любому менеджеру без нарушения его основной логики.
    
    Отличия от ObservableMixin:
    - Более универсальный подход к расширениям
    - Поддержка кастомных методов расширений
    - Автоматическое создание удобных методов-прокси
    - Поддержка цепочек расширений
    
    Пример использования:
        class MyManager(BaseManager, ManagerExtensionMixin):
            def __init__(self, name, logger=None, stats=None):
                BaseManager.__init__(self, name)
                ManagerExtensionMixin.__init__(
                    self,
                    extensions={
                        'logger': logger,
                        'stats': stats
                    }
                )
            
            def do_something(self):
                self.log_info("Выполняю операцию")
                try:
                    result = self.process()
                    self.record_metric("operations.success")
                    return result
                except Exception as e:
                    self.track_error(e)
                    raise
    """
    
    def __init__(
        self,
        extensions: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
        auto_proxy: bool = True
    ):
        """
        Инициализация mixin с опциональными расширениями.
        
        Args:
            extensions: Словарь расширений {имя: менеджер/объект}
            config: Конфигурация включения/выключения расширений {имя: bool}
            auto_proxy: Автоматически создавать методы-прокси для стандартных расширений
        """
        self._extensions: Dict[str, Any] = extensions or {}
        self._config: Dict[str, Any] = config or {}
        
        # Состояние включения/выключения расширений
        self._enabled: Dict[str, bool] = {}
        for ext_name, ext_obj in self._extensions.items():
            self._enabled[ext_name] = (
                ext_obj is not None and 
                self._config.get(ext_name, {}).get('enabled', True)
            )
        
        # Кэш для методов расширений
        self._method_cache: Dict[tuple[str, str], Optional[Callable]] = {}
        
        # Автоматическое создание прокси-методов для стандартных расширений
        if auto_proxy:
            self._create_proxy_methods()
    
    def _create_proxy_methods(self):
        """Создать удобные методы-прокси для стандартных расширений."""
        # Логирование
        if 'logger' in self._extensions:
            self.log_debug = lambda msg, **kw: self._call_extension('logger', 'debug', msg, **kw)
            self.log_info = lambda msg, **kw: self._call_extension('logger', 'info', msg, **kw)
            self.log_warning = lambda msg, **kw: self._call_extension('logger', 'warning', msg, **kw)
            self.log_error = lambda msg, **kw: self._call_extension('logger', 'error', msg, **kw)
            self.log_critical = lambda msg, **kw: self._call_extension('logger', 'critical', msg, **kw)
        
        # Статистика
        if 'stats' in self._extensions or 'statistics' in self._extensions:
            stats_name = 'stats' if 'stats' in self._extensions else 'statistics'
            self.record_metric = lambda name, value=1, tags=None: self._call_extension(
                stats_name, 'record_metric', name, value, tags or {}
            )
            self.increment = lambda name, tags=None: self._call_extension(
                stats_name, 'increment', name, tags or {}
            )
            self.record_timing = lambda name, duration, tags=None: self._call_extension(
                stats_name, 'record_timing', name, duration, tags or {}
            )
            self.gauge = lambda name, value, tags=None: self._call_extension(
                stats_name, 'gauge', name, value, tags or {}
            )
        
        # Ошибки
        if 'errors' in self._extensions or 'error' in self._extensions:
            error_name = 'errors' if 'errors' in self._extensions else 'error'
            self.track_error = lambda error, context=None: self._call_extension(
                error_name, 'track_error', error, context or {}
            )
            self.record_error = lambda error, context=None: self._call_extension(
                error_name, 'record_error', error, context or {}
            )
    
    def register_extension(self, name: str, extension: Any, enabled: bool = True, config: Optional[Dict] = None):
        """
        Регистрация нового расширения.
        
        Args:
            name: Имя расширения
            extension: Экземпляр расширения (менеджер, сервис и т.д.)
            enabled: Включено ли по умолчанию
            config: Дополнительная конфигурация расширения
        """
        self._extensions[name] = extension
        self._enabled[name] = enabled and extension is not None
        if config:
            self._config[name] = {**self._config.get(name, {}), **config}
        
        # Очищаем кэш методов для этого расширения
        self._method_cache = {k: v for k, v in self._method_cache.items() if k[0] != name}
        
        # Пересоздаем прокси-методы если нужно
        self._create_proxy_methods()
    
    def unregister_extension(self, name: str):
        """Удаление расширения."""
        self._extensions.pop(name, None)
        self._enabled.pop(name, None)
        self._config.pop(name, None)
        self._method_cache = {k: v for k, v in self._method_cache.items() if k[0] != name}
    
    def get_extension(self, name: str) -> Optional[Any]:
        """Получить расширение по имени."""
        return self._extensions.get(name)
    
    def has_extension(self, name: str) -> bool:
        """Проверить наличие расширения."""
        return name in self._extensions and self._extensions[name] is not None
    
    def enable_extension(self, name: str, enabled: bool = True):
        """Включить/выключить расширение."""
        if name in self._extensions:
            self._enabled[name] = enabled and self._extensions[name] is not None
    
    def disable_extension(self, name: str):
        """Выключить расширение."""
        self.enable_extension(name, False)
    
    def is_extension_enabled(self, name: str) -> bool:
        """Проверить включено ли расширение."""
        return self._enabled.get(name, False)
    
    def get_enabled_extensions(self) -> Set[str]:
        """Получить список включенных расширений."""
        return {name for name, enabled in self._enabled.items() if enabled}
    
    def _call_extension(self, extension_name: str, method_name: str, *args, **kwargs) -> Any:
        """
        Универсальный метод для вызова метода расширения.
        
        Args:
            extension_name: Имя расширения
            method_name: Имя метода для вызова
            *args: Позиционные аргументы
            **kwargs: Именованные аргументы
            
        Returns:
            Результат вызова метода или None если расширение не доступно
        """
        if not self.is_extension_enabled(extension_name):
            return None
        
        extension = self._extensions.get(extension_name)
        if not extension:
            return None
        
        # Проверяем кэш методов
        cache_key = (extension_name, method_name)
        method = self._method_cache.get(cache_key)
        
        # Если метода нет в кэше, получаем его и кэшируем
        if method is None and cache_key not in self._method_cache:
            try:
                method = getattr(extension, method_name, None)
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
                self._method_cache.pop(cache_key, None)
                pass  # Не падаем если расширение не работает
        
        return None
    
    @contextmanager
    def extension_context(self, extension_name: str, enabled: bool = True):
        """
        Временно изменить состояние расширения.
        
        Args:
            extension_name: Имя расширения
            enabled: Включить (True) или выключить (False)
        """
        old_state = self._enabled.get(extension_name, False)
        if extension_name in self._extensions:
            self._enabled[extension_name] = enabled and self._extensions[extension_name] is not None
        try:
            yield
        finally:
            if extension_name in self._enabled:
                self._enabled[extension_name] = old_state
    
    def call_extension_method(self, extension_name: str, method_name: str, *args, **kwargs) -> Any:
        """
        Публичный метод для вызова метода расширения.
        
        Полезен для динамических вызовов или когда нужно явно указать расширение.
        
        Args:
            extension_name: Имя расширения
            method_name: Имя метода
            *args: Позиционные аргументы
            **kwargs: Именованные аргументы
            
        Returns:
            Результат вызова метода или None
        """
        return self._call_extension(extension_name, method_name, *args, **kwargs)
    
    def get_extension_state(self) -> Dict[str, Any]:
        """
        Получить состояние всех расширений.
        
        Returns:
            Словарь с информацией о расширениях:
            - extensions: Список зарегистрированных расширений
            - enabled: Список включенных расширений
            - config: Конфигурация расширений
        """
        return {
            "extensions": list(self._extensions.keys()),
            "enabled": list(self.get_enabled_extensions()),
            "config": self._config.copy()
        }
    
    # Декораторы для автоматического использования расширений
    
    def logged(self, extension_name: str = 'logger', level: str = "info", log_args: bool = False, log_result: bool = False):
        """
        Декоратор для автоматического логирования вызовов методов.
        
        Args:
            extension_name: Имя расширения для логирования (по умолчанию 'logger')
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
                    self._call_extension(extension_name, level, f"Calling {method_name}", args=args, kwargs=kwargs)
                else:
                    self._call_extension(extension_name, level, f"Calling {method_name}")
                
                try:
                    result = func(*args, **kwargs)
                    
                    # Логирование результата
                    if log_result:
                        self._call_extension(extension_name, level, f"{method_name} completed", result=result)
                    
                    return result
                except Exception as e:
                    self._call_extension(extension_name, 'error', f"{method_name} failed: {str(e)}")
                    self._call_extension('errors', 'track_error', e, {"method": method_name})
                    raise
            
            return wrapper
        return decorator
    
    def timed(self, extension_name: str = 'stats', metric_name: str = None, tags: Dict[str, str] = None):
        """
        Декоратор для автоматического измерения времени выполнения.
        
        Args:
            extension_name: Имя расширения статистики (по умолчанию 'stats')
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
                    self._call_extension(extension_name, 'record_timing', metric, duration, tags or {})
                    return result
                except Exception as e:
                    duration = time.time() - start_time
                    self._call_extension(extension_name, 'record_timing', f"{metric}.error", duration, tags or {})
                    raise
            
            return wrapper
        return decorator
    
    def monitored(self, logger_ext: str = 'logger', stats_ext: str = 'stats', level: str = "info", metric_name: str = None):
        """
        Комбинированный декоратор для логирования и статистики.
        
        Args:
            logger_ext: Имя расширения для логирования
            stats_ext: Имя расширения для статистики
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
                self._call_extension(logger_ext, level, f"Executing {method_name}")
                self._call_extension(stats_ext, 'increment', f"{metric}.calls")
                
                try:
                    result = func(*args, **kwargs)
                    duration = time.time() - start_time
                    
                    # Логирование успеха
                    self._call_extension(logger_ext, level, f"{method_name} completed in {duration:.3f}s")
                    self._call_extension(stats_ext, 'record_timing', f"{metric}.duration", duration)
                    self._call_extension(stats_ext, 'increment', f"{metric}.success")
                    
                    return result
                except Exception as e:
                    duration = time.time() - start_time
                    
                    # Логирование ошибки
                    self._call_extension(logger_ext, 'error', f"{method_name} failed: {str(e)}")
                    self._call_extension('errors', 'track_error', e, {"method": method_name})
                    self._call_extension(stats_ext, 'record_timing', f"{metric}.error_duration", duration)
                    self._call_extension(stats_ext, 'increment', f"{metric}.errors")
                    
                    raise
            
            return wrapper
        return decorator

