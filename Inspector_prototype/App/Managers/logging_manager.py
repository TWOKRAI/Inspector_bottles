# -*- coding: utf-8 -*-
"""
Менеджер логирования для App Inspector.
Централизованное управление логированием и генерацией отчетов.
"""
import os
import logging
from logging.handlers import RotatingFileHandler
from typing import Optional, Dict, Any
from PyQt5.QtCore import QObject, pyqtSignal
from queue import Empty


class LoggingManager(QObject):
    """
    Централизованный менеджер логирования.
    Предоставляет структурированное логирование и интеграцию с процессом debug_logger.
    """
    
    # Сигналы Qt для уведомления о событиях логирования
    report_generated = pyqtSignal(str)  # report_path
    log_message = pyqtSignal(str, str)  # level, message
    
    def __init__(self, 
                 logs_dir: Optional[str] = None,
                 queue_manager: Optional[Any] = None,
                 app_name: str = "InspectorApp"):
        """
        Инициализация менеджера логирования.
        
        Args:
            logs_dir: Директория для логов (по умолчанию App/Data/logs)
            queue_manager: QueueManager для интеграции с процессом debug_logger
            app_name: Имя приложения для логирования
        """
        super().__init__()
        
        # Определяем директорию для логов
        if logs_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            logs_dir = os.path.join(base_dir, 'App', 'Data', 'logs')
        
        self.logs_dir = os.path.abspath(logs_dir)
        self.debug_logs_dir = os.path.join(os.path.dirname(self.logs_dir), 'debug_logs')
        self.queue_manager = queue_manager
        self.app_name = app_name
        
        # Создаём директории если их нет
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.debug_logs_dir, exist_ok=True)
        
        # Настраиваем логирование
        self._setup_logging()
        
        # Логгер для использования в коде
        self.logger = logging.getLogger(self.app_name)
    
    def _setup_logging(self):
        """Настройка структурированного логирования"""
        # Получаем или создаём логгер
        logger = logging.getLogger(self.app_name)
        logger.setLevel(logging.DEBUG)
        
        # Удаляем существующие handlers чтобы избежать дублирования
        logger.handlers.clear()
        
        # Формат логов
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Файловый handler с ротацией
        log_file = os.path.join(self.logs_dir, f'{self.app_name}.log')
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        # Консольный handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # Обработчик для отправки сигналов Qt
        qt_handler = QtLogHandler(self)
        qt_handler.setLevel(logging.WARNING)  # Только предупреждения и ошибки
        qt_handler.setFormatter(formatter)
        logger.addHandler(qt_handler)
    
    def debug(self, message: str, *args, **kwargs):
        """Логирование на уровне DEBUG"""
        self.logger.debug(message, *args, **kwargs)
    
    def info(self, message: str, *args, **kwargs):
        """Логирование на уровне INFO"""
        self.logger.info(message, *args, **kwargs)
    
    def warning(self, message: str, *args, **kwargs):
        """Логирование на уровне WARNING"""
        self.logger.warning(message, *args, **kwargs)
    
    def error(self, message: str, exc_info: bool = False, *args, **kwargs):
        """Логирование на уровне ERROR"""
        if exc_info:
            kwargs['exc_info'] = True
        self.logger.error(message, *args, **kwargs)
    
    def critical(self, message: str, exc_info: bool = False, *args, **kwargs):
        """Логирование на уровне CRITICAL"""
        if exc_info:
            kwargs['exc_info'] = True
        self.logger.critical(message, *args, **kwargs)
    
    def generate_debug_report(self, frame_id: str = "current_frame") -> bool:
        """
        Генерация debug отчета через процесс debug_logger.
        
        Args:
            frame_id: ID кадра для отчета (по умолчанию "current_frame")
            
        Returns:
            bool: True если команда отправлена успешно
        """
        if not self.queue_manager:
            self.warning("QueueManager not available, cannot generate debug report")
            return False
        
        if not hasattr(self.queue_manager, 'control_debug_logger'):
            self.warning("control_debug_logger queue not available")
            return False
        
        try:
            # Очищаем очередь перед отправкой команды
            control_queue = self.queue_manager.control_debug_logger
            while not control_queue.empty():
                try:
                    control_queue.get_nowait()
                except Empty:
                    break
            
            # Отправляем команду генерации отчета
            control_queue.put({
                'command': 'generate_report',
                'frame_id': frame_id
            })
            
            self.info(f"Debug report generation command sent for frame_id: {frame_id}")
            return True
            
        except Exception as e:
            self.error(f"Failed to send debug report command: {e}", exc_info=True)
            return False
    
    def check_report_status(self) -> Optional[str]:
        """
        Проверка статуса генерации отчета.
        
        Returns:
            str: Путь к сгенерированному отчету или None если не готов
        """
        if not self.queue_manager or not hasattr(self.queue_manager, 'control_debug_logger'):
            return None
        
        try:
            control_queue = self.queue_manager.control_debug_logger
            if control_queue.empty():
                return None
            
            control = control_queue.get_nowait()
            if control.get('command') == 'report_generated':
                report_path = control.get('report_path')
                if report_path:
                    self.info(f"Debug report generated: {report_path}")
                    self.report_generated.emit(report_path)
                return report_path
            
            # Возвращаем обратно если это не наш ответ
            control_queue.put(control)
            return None
            
        except Empty:
            return None
        except Exception as e:
            self.error(f"Error checking report status: {e}", exc_info=True)
            return None
    
    def get_logs_directory(self) -> str:
        """Получить директорию для обычных логов"""
        return self.logs_dir
    
    def get_debug_logs_directory(self) -> str:
        """Получить директорию для debug отчетов"""
        return self.debug_logs_dir
    
    def open_logs_directory(self):
        """Открыть директорию с логами в проводнике"""
        try:
            from PyQt5.QtGui import QDesktopServices
            from PyQt5.QtCore import QUrl
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.logs_dir))
        except Exception as e:
            self.error(f"Failed to open logs directory: {e}", exc_info=True)
    
    def open_debug_logs_directory(self):
        """Открыть директорию с debug отчетами в проводнике"""
        try:
            from PyQt5.QtGui import QDesktopServices
            from PyQt5.QtCore import QUrl
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.debug_logs_dir))
        except Exception as e:
            self.error(f"Failed to open debug logs directory: {e}", exc_info=True)
    
    def set_log_level(self, level: str):
        """
        Установить уровень логирования.
        
        Args:
            level: Уровень логирования ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
        """
        level_map = {
            'DEBUG': logging.DEBUG,
            'INFO': logging.INFO,
            'WARNING': logging.WARNING,
            'ERROR': logging.ERROR,
            'CRITICAL': logging.CRITICAL,
        }
        
        log_level = level_map.get(level.upper(), logging.INFO)
        self.logger.setLevel(log_level)
        
        # Обновляем уровень для всех handlers
        for handler in self.logger.handlers:
            if isinstance(handler, (RotatingFileHandler, logging.StreamHandler)):
                handler.setLevel(log_level)
        
        self.info(f"Log level set to {level.upper()}")


class QtLogHandler(logging.Handler):
    """Кастомный handler для отправки логов через Qt сигналы"""
    
    def __init__(self, logging_manager: LoggingManager):
        super().__init__()
        self.logging_manager = logging_manager
    
    def emit(self, record):
        """Отправка лога через Qt сигнал"""
        try:
            msg = self.format(record)
            level = logging.getLevelName(record.levelno)
            self.logging_manager.log_message.emit(level, msg)
        except Exception:
            self.handleError(record)
