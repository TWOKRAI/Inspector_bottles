from typing import Any, Optional, Dict, Callable
from abc import ABC, abstractmethod


class BaseAdapter(ABC):
    """
    Базовый абстрактный класс для всех адаптеров менеджеров.
    
    Адаптер инкапсулирует логику взаимодействия с менеджером,
    предоставляя упрощенный и стандартизированный интерфейс.
    
    Attributes:
        manager: Экземпляр менеджера, к которому предоставляется адаптер
        process: Ссылка на родительский процесс
        adapter_name: Уникальное имя адаптера
    """
    
    def __init__(self, manager: Any, process: Optional[Any] = None, adapter_name: str = None, logging_enabled: bool = True):
        """
        Инициализация базового адаптера.
        
        Args:
            manager: Экземпляр менеджера
            process: Ссылка на родительский процесс
            adapter_name: Уникальное имя адаптера (по умолчанию класс адаптера)
            logging_enabled: Включено ли логирование (по умолчанию True)
        """
        self.manager = manager
        self.process = process
        self.adapter_name = adapter_name or self.__class__.__name__
        self._initialized = False
        self._logging_enabled = logging_enabled
    
    @abstractmethod
    def setup(self) -> bool:
        """
        Настройка адаптера и интеграция с менеджером.
        Должен быть реализован в дочерних классах.
        
        Returns:
            bool: True если настройка успешна
        """
        pass
    
    def is_initialized(self) -> bool:
        """
        Проверка инициализации адаптера.
        
        Returns:
            bool: True если адаптер инициализирован
        """
        return self._initialized
    
    def get_manager(self) -> Any:
        """
        Получение экземпляра менеджера.
        
        Returns:
            Any: Экземпляр менеджера
        """
        return self.manager
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Получение статистики адаптера.
        
        Returns:
            Dict[str, Any]: Словарь со статистикой
        """
        return {
            "adapter_name": self.adapter_name,
            "initialized": self._initialized,
            "manager": getattr(self.manager, 'manager_name', 'unknown') if hasattr(self.manager, 'manager_name') else 'unknown'
        }
    
    def enable_logging(self, enabled: bool = True):
        """
        Включить/выключить логирование в адаптере.
        
        Args:
            enabled: Включить (True) или выключить (False) логирование
        """
        self._logging_enabled = enabled
    
    def is_logging_enabled(self) -> bool:
        """
        Проверить включено ли логирование.
        
        Returns:
            bool: True если логирование включено
        """
        return self._logging_enabled
    
    def _log(self, level: str, message: str, context: str = None):
        """
        Вспомогательный метод для логирования.
        
        Использует ObservableMixin менеджера если доступен (логирование, мониторинг, статистика).
        Если менеджер не использует ObservableMixin, пытается использовать логгер процесса.
        
        Приоритеты логирования:
        1. ObservableMixin менеджера (если доступен) - предпочтительный способ
        2. LoggerManager процесса (обратная совместимость)
        3. Fallback на print (если ничего не доступно)
        
        Args:
            level: Уровень логирования (debug, info, warning, error)
            message: Сообщение
            context: Контекст логирования
        """
        # Проверяем включено ли логирование
        if not self._logging_enabled:
            return
        
        # Проверяем использует ли менеджер ObservableMixin
        manager_has_observable = (self.manager and 
                                  hasattr(self.manager, '_managers') and 
                                  hasattr(self.manager, '_call_manager'))
        
        # Приоритет 1: Использовать ObservableMixin менеджера через _call_manager
        # ObservableMixin взаимодействует с LoggerManager - это предпочтительный способ
        # Вся логика логирования в LoggerManager, ObservableMixin только передает вызов
        if manager_has_observable:
            try:
                # Используем _call_manager для вызова logger менеджера
                # ObservableMixin передаст вызов в LoggerManager если он зарегистрирован
                result = self.manager._call_manager('logger', level, message, module=context or self.adapter_name)
                if result is not None:
                    return
            except Exception:
                pass
            
            # Приоритет 1b: Прямой доступ к методам логирования ObservableMixin (fallback)
            # Если _call_manager не работает, пробуем прямые методы ObservableMixin
            if hasattr(self.manager, '_log_info'):
                try:
                    log_method = getattr(self.manager, f'_log_{level}', None)
                    if log_method and callable(log_method):
                        log_method(message, module=context or self.adapter_name)
                        return
                except Exception:
                    pass
        
        # Приоритет 2: Использовать логгер процесса напрямую (обратная совместимость)
        # Это для случаев когда менеджер не использует ObservableMixin
        # Логика логирования все равно в LoggerManager процесса
        if self.process and hasattr(self.process, 'logger_manager'):
            try:
                logger_manager = self.process.logger_manager
                if logger_manager:
                    log_method = getattr(logger_manager, level.lower(), None)
                    if log_method and callable(log_method):
                        log_method(message, context or self.adapter_name)
                        return
            except Exception:
                pass
        
        # Fallback: обычный print (только если логирование включено)
        print(f"[{level.upper()}] {self.adapter_name}: {message}")
    
    def __str__(self) -> str:
        """
        Строковое представление адаптера.
        
        Returns:
            str: Информация об адаптере
        """
        return f"{self.adapter_name}(initialized={self._initialized})"


