"""
Единая точка входа для логирования в Multiprocess Framework.

LoggingFacade обеспечивает доступ к логированию даже когда LoggerManager
еще не инициализирован, используя fallback на стандартный logging модуль.

Использование:
    from multiprocess_framework.core.logging_facade import log
    
    # Логирование работает всегда
    log.info("Сообщение")
    log.error("Ошибка", exc_info=True)
    
    # После инициализации LoggerManager автоматически используется он
    logger_manager = LoggerManager(...)
    logger_manager.initialize()
    log.set_logger_manager(logger_manager)
"""

import logging
from typing import Optional, Any, Dict
from pathlib import Path


class LoggingFacade:
    """
    Единая точка входа для логирования.
    
    Работает даже если LoggerManager еще не инициализирован,
    используя fallback на стандартный logging модуль Python.
    """
    
    _instance: Optional['LoggingFacade'] = None
    _logger_manager: Optional[Any] = None
    _fallback_logger: Optional[logging.Logger] = None
    
    def __new__(cls):
        """Singleton паттерн."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_fallback()
        return cls._instance
    
    def _init_fallback(self):
        """Инициализация fallback logger."""
        self._fallback_logger = logging.getLogger('multiprocess_framework')
        if not self._fallback_logger.handlers:
            # Настраиваем базовый handler если его нет
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            handler.setFormatter(formatter)
            self._fallback_logger.addHandler(handler)
            self._fallback_logger.setLevel(logging.INFO)
    
    @classmethod
    def set_logger_manager(cls, manager: Any):
        """
        Установить LoggerManager для использования вместо fallback.
        
        Args:
            manager: Экземпляр LoggerManager
        """
        cls._logger_manager = manager
    
    @classmethod
    def get_logger(cls) -> Any:
        """
        Получить текущий logger (LoggerManager или fallback).
        
        Returns:
            LoggerManager или стандартный logging.Logger
        """
        if cls._logger_manager and hasattr(cls._logger_manager, 'is_initialized'):
            if cls._logger_manager.is_initialized:
                return cls._logger_manager
        
        # Используем fallback
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance._fallback_logger
    
    @classmethod
    def info(cls, message: str, **kwargs):
        """Логирование информации."""
        logger = cls.get_logger()
        if hasattr(logger, 'info'):
            if isinstance(logger, logging.Logger):
                logger.info(message, **kwargs)
            else:
                # LoggerManager
                logger.info(message, **kwargs)
        else:
            print(f"INFO: {message}")
    
    @classmethod
    def debug(cls, message: str, **kwargs):
        """Логирование отладочной информации."""
        logger = cls.get_logger()
        if hasattr(logger, 'debug'):
            if isinstance(logger, logging.Logger):
                logger.debug(message, **kwargs)
            else:
                logger.debug(message, **kwargs)
        else:
            print(f"DEBUG: {message}")
    
    @classmethod
    def warning(cls, message: str, **kwargs):
        """Логирование предупреждения."""
        logger = cls.get_logger()
        if hasattr(logger, 'warning'):
            if isinstance(logger, logging.Logger):
                logger.warning(message, **kwargs)
            else:
                logger.warning(message, **kwargs)
        else:
            print(f"WARNING: {message}")
    
    @classmethod
    def error(cls, message: str, exc_info: bool = False, **kwargs):
        """Логирование ошибки."""
        logger = cls.get_logger()
        if hasattr(logger, 'error'):
            if isinstance(logger, logging.Logger):
                logger.error(message, exc_info=exc_info, **kwargs)
            else:
                logger.error(message, exc_info=exc_info, **kwargs)
        else:
            print(f"ERROR: {message}")
            if exc_info:
                import traceback
                traceback.print_exc()
    
    @classmethod
    def critical(cls, message: str, **kwargs):
        """Логирование критической ошибки."""
        logger = cls.get_logger()
        if hasattr(logger, 'critical'):
            if isinstance(logger, logging.Logger):
                logger.critical(message, **kwargs)
            else:
                logger.critical(message, **kwargs)
        else:
            print(f"CRITICAL: {message}")
    
    @classmethod
    def exception(cls, message: str, **kwargs):
        """Логирование исключения с traceback."""
        cls.error(message, exc_info=True, **kwargs)


# Глобальный экземпляр для удобного доступа
log = LoggingFacade()

