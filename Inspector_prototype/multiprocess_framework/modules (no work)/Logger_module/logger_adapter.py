"""
Адаптер для LoggerManager.

Предоставляет упрощенный интерфейс для логирования с поддержкой:
- Прямого доступа к LoggerManager
- Маршрутизации через Message_module
- Конвертации между старым и новым API
"""

from typing import Any, Optional, Dict, Union
from ..Base_manager_module.base_adapter import BaseAdapter
from .config import LogLevel, LogScope


class LoggerAdapter(BaseAdapter):
    """
    Адаптер для LoggerManager (инструмент интеграции с процессом).
    
    Предоставляет дополнительную функциональность для LoggerManager:
    - Конвертация уровней логирования (строка -> LogLevel)
    - Автоматическое определение scope по умолчанию
    - Управление message routing
    
    Основная функциональность (log, debug, info, warning, error, critical, system, business, etc.)
    доступна напрямую через менеджер - адаптер не дублирует эти методы.
    """
    
    def __init__(self, logger_manager: Any, process: Optional[Any] = None):
        """
        Инициализация адаптера логгера.
        
        Args:
            logger_manager: Экземпляр LoggerManager
            process: Ссылка на родительский процесс
        """
        super().__init__(logger_manager, process, "LoggerAdapter")
        self.enable_message_routing = False  # Флаг для маршрутизации через Message_module
    
    def setup(self) -> bool:
        """
        Настройка адаптера логгера.
        
        Returns:
            bool: True если настройка успешна
        """
        try:
            if not self.manager:
                self._log("error", "Manager is not set")
                return False
            
            self._initialized = True
            self._log("info", "LoggerAdapter initialized")
            return True
            
        except Exception as e:
            self._log("error", f"Setup failed - {e}")
            return False
    
    def set_message_routing(self, enable: bool = True):
        """
        Включение/выключение логирования через Message_module.
        
        Args:
            enable: True для включения маршрутизации
        """
        self.enable_message_routing = enable
        if self.manager and hasattr(self.manager, 'enable'):
            self.manager.enable('message_routing', enable)
    
    def log_with_auto_scope(
        self,
        level: Union[str, LogLevel],
        message: str,
        context: str = None,
        scope: Optional[LogScope] = None,
        **kwargs
    ) -> bool:
        """
        Удобный метод логирования с автоматическим определением scope и конвертацией уровня.
        
        Используйте этот метод, если нужно автоматическое определение scope на основе уровня логирования.
        Для прямого логирования используйте методы менеджера: manager.log(), manager.info(), etc.
        
        Args:
            level: Уровень логирования (строка или LogLevel)
            message: Текст сообщения
            context: Контекст/модуль
            scope: Область логирования (опционально, определяется автоматически если не указано)
            **kwargs: Дополнительные параметры
            
        Returns:
            bool: True если логирование успешно
        """
        try:
            if not self.manager:
                return False
            
            # Конвертируем уровень в LogLevel если нужно
            log_level = self._convert_level(level)
            if log_level is None:
                return False
            
            # Определяем область логирования автоматически если не указана
            if scope is None:
                scope = self._get_default_scope(log_level)
            
            # Определяем модуль
            module = context or self._get_default_module()
            
            # Логируем через менеджер
            self.manager.log(scope, log_level, message, module, **kwargs)
            
            return True
            
        except Exception as e:
            self._log("error", f"Log failed - {e}")
            return False
    
    def _convert_level(self, level: Union[str, LogLevel]) -> Optional[LogLevel]:
        """
        Конвертирует уровень логирования в LogLevel.
        
        Args:
            level: Уровень (строка или LogLevel)
            
        Returns:
            LogLevel или None если не удалось конвертировать
        """
        if isinstance(level, LogLevel):
            return level
        
        if isinstance(level, str):
            level_upper = level.upper()
            try:
                return LogLevel[level_upper]
            except KeyError:
                # Пробуем конвертировать из формата Message_module (lowercase)
                level_mapping = {
                    'debug': LogLevel.DEBUG,
                    'info': LogLevel.INFO,
                    'warning': LogLevel.WARNING,
                    'error': LogLevel.ERROR,
                    'critical': LogLevel.CRITICAL
                }
                return level_mapping.get(level.lower())
        
        return None
    
    def _get_default_scope(self, level: LogLevel) -> LogScope:
        """
        Определяет область логирования по умолчанию на основе уровня.
        
        Args:
            level: Уровень логирования
            
        Returns:
            LogScope
        """
        # Для ошибок и критических - SYSTEM
        if level in [LogLevel.ERROR, LogLevel.CRITICAL]:
            return LogScope.SYSTEM
        
        # Для предупреждений - SYSTEM
        if level == LogLevel.WARNING:
            return LogScope.SYSTEM
        
        # Для остального - BUSINESS
        return LogScope.BUSINESS
    
    def _get_default_module(self) -> str:
        """Получает модуль по умолчанию из контекста процесса."""
        if self.process and hasattr(self.process, 'name'):
            return self.process.name
        return "app"
    
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Получение статистики адаптера.
        
        Returns:
            Dict[str, Any]: Статистика адаптера и менеджера
        """
        stats = super().get_stats()
        stats.update({
            "message_routing_enabled": self.enable_message_routing
        })
        
        # Добавляем статистику менеджера если доступна
        if self.manager and hasattr(self.manager, 'get_stats'):
            try:
                manager_stats = self.manager.get_stats()
                stats["manager_stats"] = manager_stats
            except Exception:
                pass
        
        return stats
