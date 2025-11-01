import logging
import logging.handlers
import time
import json
from typing import Dict, List, Any, Optional, Union
from enum import Enum

class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

class LogHandlerType(Enum):
    CONSOLE = "console"
    FILE = "file"
    BUFFER = "buffer"
    ROTATING_FILE = "rotating_file"

class LoggerManager:
    """
    Независимый менеджер логирования.
    Отвечает только за запись, хранение и фильтрацию логов.
    """
    
    def __init__(self, name: str, default_level: LogLevel = LogLevel.INFO):
        self.name = name
        self.default_level = default_level
        self.is_running = False
        
        # Основной логгер
        self.logger = logging.getLogger(f"ProcessModule.{name}")
        self.logger.setLevel(logging.DEBUG)  # Самый низкий уровень, фильтруем обработчиками
        
        # Буфер для хранения последних логов
        self.log_buffer = []
        self.max_buffer_size = 1000
        
        # Словарь обработчиков
        self.handlers = {}
        
        # Инициализация
        self._setup_default_handlers()
        
    def _setup_default_handlers(self):
        """Настройка обработчиков по умолчанию"""
        # Консольный обработчик
        self.add_handler(
            handler_type=LogHandlerType.CONSOLE,
            handler_name="default_console",
            level=self.default_level
        )
        
        # Буферный обработчик (всегда включен)
        self.add_handler(
            handler_type=LogHandlerType.BUFFER,
            handler_name="buffer",
            level=LogLevel.DEBUG  # В буфер пишем всё
        )
    
    def start(self):
        """Запуск менеджера логирования"""
        self.is_running = True
        self.info("LoggerManager started")
        
    def stop(self):
        """Остановка менеджера логирования"""
        self.is_running = False
        self.info("LoggerManager stopped")
        
        # Закрываем все обработчики
        for handler_name, handler in self.handlers.items():
            try:
                if hasattr(handler, 'close'):
                    handler.close()
            except Exception as e:
                print(f"Error closing handler {handler_name}: {e}")
    
    def add_handler(self, 
                   handler_type: LogHandlerType,
                   handler_name: str,
                   level: LogLevel = LogLevel.INFO,
                   **config) -> bool:
        """
        Добавление обработчика логирования
        
        Args:
            handler_type: Тип обработчика
            handler_name: Уникальное имя обработчика
            level: Уровень логирования для этого обработчика
            **config: Дополнительные параметры для обработчика
            
        Returns:
            bool: Успешно ли добавлен обработчик
        """
        try:
            handler = self._create_handler(handler_type, level, config)
            if handler:
                self.handlers[handler_name] = handler
                self.logger.addHandler(handler)
                self.debug(f"Added log handler: {handler_name} ({handler_type.value})")
                return True
        except Exception as e:
            self._fallback_log(f"Error adding handler {handler_name}: {e}")
            
        return False
    
    def _create_handler(self, handler_type: LogHandlerType, level: LogLevel, config: Dict) -> Optional[logging.Handler]:
        """Создание обработчика указанного типа"""
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        try:
            if handler_type == LogHandlerType.CONSOLE:
                handler = logging.StreamHandler()
                
            elif handler_type == LogHandlerType.FILE:
                filename = config.get('filename', f'{self.name}.log')
                handler = logging.FileHandler(filename, encoding='utf-8')
                
            elif handler_type == LogHandlerType.ROTATING_FILE:
                filename = config.get('filename', f'{self.name}.log')
                max_bytes = config.get('max_bytes', 10 * 1024 * 1024)  # 10MB
                backup_count = config.get('backup_count', 5)
                handler = logging.handlers.RotatingFileHandler(
                    filename, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8'
                )
                
            elif handler_type == LogHandlerType.BUFFER:
                handler = self._create_buffer_handler()
                
            else:
                self._fallback_log(f"Unknown handler type: {handler_type}")
                return None
            
            # Настройка обработчика
            handler.setLevel(getattr(logging, level.value))
            handler.setFormatter(formatter)
            return handler
            
        except Exception as e:
            self._fallback_log(f"Error creating handler {handler_type}: {e}")
            return None
    
    def _create_buffer_handler(self) -> logging.Handler:
        """Создание обработчика для буферизации логов в памяти"""
        class BufferHandler(logging.Handler):
            def __init__(self, manager):
                super().__init__()
                self.manager = manager
                self.setLevel(logging.DEBUG)
                
            def emit(self, record):
                try:
                    log_entry = {
                        'timestamp': time.time(),
                        'level': record.levelname,
                        'message': self.format(record),
                        'module': record.module,
                        'function': record.funcName,
                        'line': record.lineno
                    }
                    self.manager._add_to_buffer(log_entry)
                except Exception as e:
                    print(f"Buffer handler error: {e}")
        
        return BufferHandler(self)
    
    def _add_to_buffer(self, log_entry: Dict):
        """Добавление записи в буфер"""
        self.log_buffer.append(log_entry)
        
        # Ограничиваем размер буфера
        if len(self.log_buffer) > self.max_buffer_size:
            self.log_buffer.pop(0)
    
    def remove_handler(self, handler_name: str) -> bool:
        """Удаление обработчика"""
        if handler_name in self.handlers:
            handler = self.handlers[handler_name]
            self.logger.removeHandler(handler)
            
            if hasattr(handler, 'close'):
                handler.close()
                
            del self.handlers[handler_name]
            self.debug(f"Removed log handler: {handler_name}")
            return True
        
        return False
    
    def set_level(self, handler_name: str, level: LogLevel) -> bool:
        """Установка уровня логирования для обработчика"""
        if handler_name in self.handlers:
            self.handlers[handler_name].setLevel(getattr(logging, level.value))
            self.debug(f"Set level for {handler_name}: {level.value}")
            return True
        return False
    
    def set_global_level(self, level: LogLevel):
        """Установка глобального уровня логирования для всех обработчиков"""
        for handler_name in self.handlers:
            self.set_level(handler_name, level)
    
    # Основные методы логирования
    def debug(self, message: str):
        """Запись отладочного сообщения"""
        self.logger.debug(message)
    
    def info(self, message: str):
        """Запись информационного сообщения"""
        self.logger.info(message)
    
    def warning(self, message: str):
        """Запись предупреждения"""
        self.logger.warning(message)
    
    def error(self, message: str):
        """Запись ошибки"""
        self.logger.error(message)
    
    def critical(self, message: str):
        """Запись критической ошибки"""
        self.logger.critical(message)
    
    # Методы для работы с буфером логов
    def get_logs(self, 
                 filters: Optional[Dict] = None,
                 max_entries: int = 100) -> List[Dict]:
        """
        Получение логов из буфера с фильтрацией
        
        Args:
            filters: Словарь с фильтрами
            max_entries: Максимальное количество записей
            
        Returns:
            List[Dict]: Отфильтрованные логи
        """
        if not self.log_buffer:
            return []
        
        filters = filters or {}
        filtered_logs = []
        
        # Идем с конца (последние логи сначала)
        for log_entry in reversed(self.log_buffer):
            if self._log_matches_filters(log_entry, filters):
                filtered_logs.append(log_entry)
                if len(filtered_logs) >= max_entries:
                    break
        
        return list(reversed(filtered_logs))  # Возвращаем в хронологическом порядке
    
    def _log_matches_filters(self, log_entry: Dict, filters: Dict) -> bool:
        """Проверка соответствия лога фильтрам"""
        for key, value in filters.items():
            if key == 'level' and log_entry.get('level') != value:
                return False
            elif key == 'level_in' and log_entry.get('level') not in value:
                return False
            elif key == 'module' and value not in log_entry.get('module', ''):
                return False
            elif key == 'function' and value not in log_entry.get('function', ''):
                return False
            elif key == 'message_contains' and value not in log_entry.get('message', ''):
                return False
            elif key == 'timestamp_from' and log_entry.get('timestamp', 0) < value:
                return False
            elif key == 'timestamp_to' and log_entry.get('timestamp', 0) > value:
                return False
        
        return True
    
    def clear_buffer(self):
        """Очистка буфера логов"""
        self.log_buffer.clear()
        self.debug("Log buffer cleared")
    
    def get_buffer_stats(self) -> Dict:
        """Получение статистики буфера"""
        if not self.log_buffer:
            return {'size': 0, 'levels': {}}
        
        levels = {}
        for log in self.log_buffer:
            level = log.get('level', 'UNKNOWN')
            levels[level] = levels.get(level, 0) + 1
        
        return {
            'size': len(self.log_buffer),
            'levels': levels,
            'oldest': min(log['timestamp'] for log in self.log_buffer) if self.log_buffer else 0,
            'newest': max(log['timestamp'] for log in self.log_buffer) if self.log_buffer else 0
        }
    
    def get_handler_info(self) -> Dict:
        """Получение информации об обработчиках"""
        info = {}
        for name, handler in self.handlers.items():
            info[name] = {
                'type': type(handler).__name__,
                'level': logging.getLevelName(handler.level),
                'active': True
            }
        return info
    
    def _fallback_log(self, message: str):
        """Резервное логирование при проблемах с основными обработчиками"""
        print(f"[FALLBACK] {self.name}: {message}")
    
    # Методы для интеграции с ProcessModule
    def get_status(self) -> Dict:
        """Получение статуса менеджера для мониторинга"""
        return {
            'running': self.is_running,
            'buffer_stats': self.get_buffer_stats(),
            'handlers': self.get_handler_info(),
            'default_level': self.default_level.value
        }
    
    def is_ready(self) -> bool:
        """Проверка готовности менеджера"""
        return self.is_running and len(self.handlers) > 0
    

if __name__ == "__main__":
    logger = LoggerManager("TestProcess", LogLevel.DEBUG)

    # Запуск
    logger.start()

    # Добавление обработчиков
    logger.add_handler(
        LogHandlerType.FILE,
        "main_file",
        LogLevel.INFO,
        filename="process.log"
    )

    logger.add_handler(
        LogHandlerType.ROTATING_FILE,
        "rotating_file", 
        LogLevel.DEBUG,
        filename="debug.log",
        max_bytes=5*1024*1024,  # 5MB
        backup_count=3
    )

    # Логирование
    logger.debug("Отладочное сообщение")
    logger.info("Информационное сообщение")
    logger.warning("Предупреждение")
    logger.error("Ошибка обработки")

    # Получение логов с фильтрацией
    error_logs = logger.get_logs(filters={'level': 'ERROR'})
    recent_logs = logger.get_logs(filters={'timestamp_from': time.time() - 3600})

    # Статистика
    stats = logger.get_buffer_stats()
    print(f"Всего логов в буфере: {stats['size']}")

    # Остановка
    logger.stop()