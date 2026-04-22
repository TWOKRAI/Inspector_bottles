# -*- coding: utf-8 -*-
"""
Менеджер обработки ошибок для App Inspector.
Централизованная обработка исключений и ошибок приложения.
"""
from typing import Optional, Callable, Any, Dict
from functools import wraps
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QMessageBox


class ErrorManager(QObject):
    """
    Централизованный менеджер обработки ошибок.
    Предоставляет единую точку обработки исключений с логированием и уведомлениями пользователя.
    """
    
    # Сигналы Qt для уведомления об ошибках
    error_occurred = pyqtSignal(str, str, object)  # title, message, exception
    critical_error = pyqtSignal(str, str, object)  # title, message, exception
    
    def __init__(self, logging_manager: Optional[Any] = None, window_manager: Optional[Any] = None):
        """
        Инициализация менеджера ошибок.
        
        Args:
            logging_manager: LoggingManager для логирования ошибок
            window_manager: WindowManager для показа сообщений пользователю
        """
        super().__init__()
        self.logging_manager = logging_manager
        self.window_manager = window_manager
        
        # Статистика ошибок
        self.error_count = 0
        self.critical_count = 0
        self.error_history: list = []
        # Очередь/буфер для ошибок роутинга и доставки (контракт ErrorManager из архитектуры)
        self._reported_errors: list = []
        
        # Подключаем сигналы к обработчикам
        self.error_occurred.connect(self._on_error_occurred)
        self.critical_error.connect(self._on_critical_error)
    
    def report(self, error_type: str, context: Dict[str, Any]) -> None:
        """
        Контракт для ошибок роутинга и доставки (архитектура).
        Роутер/обработчик при ошибке вызывает error_manager.report(type, context).

        Args:
            error_type: ROUTING_NOT_FOUND, PROCESS_UNREACHABLE, MESSAGE_LOST и т.д.
            context: dict (register, field, process_id, channel, message_id, exception и т.д.)
        """
        entry = {"type": error_type, "context": dict(context), "timestamp": self._get_timestamp()}
        self._reported_errors.append(entry)
        if len(self._reported_errors) > 100:
            self._reported_errors.pop(0)
        if self.logging_manager:
            self.logging_manager.warning(
                f"ErrorManager.report: {error_type}",
                extra=context,
            )
        # Опционально: эмит сигнала для UI
        self.error_occurred.emit(
            f"Ошибка: {error_type}",
            str(context),
            None,
        )

    def get_reported_errors(self) -> list:
        """Вернуть последние отчётные ошибки (для отладки/UI)."""
        return list(self._reported_errors)

    def clear_reported_errors(self) -> None:
        """Очистить буфер отчётных ошибок."""
        self._reported_errors.clear()

    def handle_error(self, error: Exception, context: str = "", show_to_user: bool = True, 
                    level: str = "error") -> bool:
        """
        Обработка ошибки.
        
        Args:
            error: Исключение для обработки
            context: Контекст где произошла ошибка (например, "RecipeManager.save_recipe")
            show_to_user: Показывать ли сообщение пользователю
            level: Уровень ошибки ('error' или 'critical')
            
        Returns:
            bool: True если ошибка обработана успешно
        """
        error_type = type(error).__name__
        error_message = str(error)
        
        # Формируем сообщение для пользователя
        user_message = self._format_user_message(error, context)
        
        # Логируем ошибку
        if self.logging_manager:
            if level == "critical":
                self.logging_manager.critical(
                    f"Critical error in {context}: {error_message}",
                    exc_info=True
                )
            else:
                self.logging_manager.error(
                    f"Error in {context}: {error_message}",
                    exc_info=True
                )
        
        # Обновляем статистику
        self.error_count += 1
        if level == "critical":
            self.critical_count += 1
        
        # Сохраняем в историю
        self.error_history.append({
            'type': error_type,
            'message': error_message,
            'context': context,
            'level': level,
            'timestamp': self._get_timestamp()
        })
        
        # Ограничиваем размер истории (последние 100 ошибок)
        if len(self.error_history) > 100:
            self.error_history.pop(0)
        
        # Показываем пользователю если нужно
        if show_to_user:
            if level == "critical":
                self.critical_error.emit("Критическая ошибка", user_message, error)
            else:
                self.error_occurred.emit("Ошибка", user_message, error)
        
        return True
    
    def _format_user_message(self, error: Exception, context: str) -> str:
        """
        Форматирование сообщения об ошибке для пользователя.
        
        Args:
            error: Исключение
            context: Контекст ошибки
            
        Returns:
            str: Отформатированное сообщение
        """
        error_type = type(error).__name__
        error_message = str(error)
        
        # Понятные сообщения для пользователя
        user_friendly_messages = {
            'FileNotFoundError': 'Файл не найден',
            'PermissionError': 'Нет доступа к файлу',
            'ValueError': 'Некорректное значение',
            'KeyError': 'Отсутствует необходимый параметр',
            'TypeError': 'Некорректный тип данных',
            'ConnectionError': 'Ошибка подключения',
            'TimeoutError': 'Превышено время ожидания',
        }
        
        friendly_type = user_friendly_messages.get(error_type, error_type)
        
        if context:
            message = f"Произошла ошибка в {context}:\n{friendly_type}: {error_message}"
        else:
            message = f"Произошла ошибка:\n{friendly_type}: {error_message}"
        
        return message
    
    def _on_error_occurred(self, title: str, message: str, exception: Exception):
        """Обработчик сигнала error_occurred - показывает сообщение пользователю"""
        if self.window_manager and hasattr(self.window_manager, 'show_message'):
            # Используем существующий метод показа сообщений
            self.window_manager.show_message(f"{title}: {message}")
        else:
            # Fallback: показываем через QMessageBox
            try:
                from PyQt5.QtWidgets import QMessageBox
                msg_box = QMessageBox()
                msg_box.setIcon(QMessageBox.Warning)
                msg_box.setWindowTitle(title)
                msg_box.setText(message)
                msg_box.setStandardButtons(QMessageBox.Ok)
                msg_box.exec_()
            except Exception:
                # Если даже QMessageBox не работает, просто выводим в консоль
                print(f"{title}: {message}")
    
    def _on_critical_error(self, title: str, message: str, exception: Exception):
        """Обработчик сигнала critical_error - показывает критическое сообщение"""
        if self.window_manager and hasattr(self.window_manager, 'show_message'):
            self.window_manager.show_message(f"⚠ {title}: {message}")
        else:
            try:
                from PyQt5.QtWidgets import QMessageBox
                msg_box = QMessageBox()
                msg_box.setIcon(QMessageBox.Critical)
                msg_box.setWindowTitle(title)
                msg_box.setText(message)
                msg_box.setStandardButtons(QMessageBox.Ok)
                msg_box.exec_()
            except Exception:
                print(f"CRITICAL {title}: {message}")
    
    def handle_errors(self, context: str = "", show_to_user: bool = True, level: str = "error"):
        """
        Декоратор для автоматической обработки ошибок в функциях.
        
        Args:
            context: Контекст функции (автоматически определяется если не указан)
            show_to_user: Показывать ли сообщение пользователю
            level: Уровень ошибки
            
        Пример использования:
            @error_manager.handle_errors("RecipeManager.save_recipe")
            def save_recipe(self, recipe_id, data):
                # код сохранения
                pass
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    # Определяем контекст автоматически если не указан
                    func_context = context or f"{func.__module__}.{func.__name__}"
                    self.handle_error(e, func_context, show_to_user, level)
                    return None
            return wrapper
        return decorator
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """
        Получить статистику ошибок.
        
        Returns:
            dict: Статистика ошибок
        """
        return {
            'total_errors': self.error_count,
            'critical_errors': self.critical_count,
            'recent_errors': self.error_history[-10:] if self.error_history else [],
        }
    
    def clear_statistics(self):
        """Очистить статистику ошибок"""
        self.error_count = 0
        self.critical_count = 0
        self.error_history.clear()
    
    def _get_timestamp(self) -> str:
        """Получить текущую временную метку"""
        from datetime import datetime
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
