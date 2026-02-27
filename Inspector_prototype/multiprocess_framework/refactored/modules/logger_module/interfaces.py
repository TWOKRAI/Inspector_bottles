"""
Интерфейсы для LoggerModule.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List

from ..base_manager.interfaces import IBaseManager
from .core.log_config import LogLevel, LogScope


class ILogChannel(ABC):
    """
    Интерфейс для канала логирования.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Имя канала."""
        pass
    
    @abstractmethod
    def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Записать запись лога."""
        pass
    
    @abstractmethod
    def close(self):
        """Закрыть канал."""
        pass


class ILoggerManager(IBaseManager, ABC):
    """
    Интерфейс для менеджера логирования.
    """
    
    @abstractmethod
    def log(
        self,
        scope: LogScope,
        level: LogLevel,
        message: str,
        module: str = "main",
        **extra
    ):
        """Основной метод логирования."""
        pass
    
    @abstractmethod
    def debug(self, message: str, module: str = "main", **extra):
        """Отладочное логирование."""
        pass
    
    @abstractmethod
    def info(self, message: str, module: str = "main", **extra):
        """Информационное сообщение."""
        pass
    
    @abstractmethod
    def warning(self, message: str, module: str = "main", **extra):
        """Предупреждение."""
        pass
    
    @abstractmethod
    def error(self, message: str, module: str = "main", **extra):
        """Ошибка."""
        pass
    
    @abstractmethod
    def critical(self, message: str, module: str = "main", **extra):
        """Критическая ошибка."""
        pass
    
    @abstractmethod
    def flush(self):
        """Принудительно сбросить все буферизованные логи."""
        pass
    
    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику использования."""
        pass

