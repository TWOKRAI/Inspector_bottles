import sys
from typing import Dict, Optional, Any, List
from dataclasses import dataclass


@dataclass
class WindowConfig:
    """Конфигурация окна"""
    name: str
    window_class: Any
    show_on_start: bool = False
    fullscreen: bool = False
    position: Optional[tuple] = None
    size: Optional[tuple] = None


class BaseWindowManager:
    """
    Базовый менеджер окон для управления несколькими окнами PyQt.
    Обеспечивает переключение между окнами и централизованное управление.
    """
    
    def __init__(self, process_module, app, config: Dict[str, WindowConfig] = None):
        self.process_module = process_module
        self.app = app
        self.windows: Dict[str, Any] = {}
        self.window_configs = config or {}
        self.current_window: Optional[str] = None
        self.fullscreen = False
        self.access_level = 2
        
    def initialize_windows(self):
        """Инициализация всех окон согласно конфигурации"""
        for window_name, config in self.window_configs.items():
            self.create_window(window_name, config.window_class)
            
            if config.show_on_start:
                self.show_window(window_name)
    
    def create_window(self, window_name: str, window_class, *args, **kwargs):
        """Создание окна"""
        if window_name in self.windows:
            return self.windows[window_name]
            
        window = window_class(self, *args, **kwargs)
        self.windows[window_name] = window
        return window
    
    def show_window(self, window_name: str):
        """Показать указанное окно и скрыть остальные"""
        if window_name not in self.windows:
            self.create_window(window_name, self.window_configs[window_name].window_class)
            
        # Скрываем все окна
        for name, window in self.windows.items():
            if name != window_name:
                window.hide()
        
        # Показываем целевое окно
        self.windows[window_name].show()
        self.current_window = window_name
        
        # Применяем настройки полноэкранного режима
        config = self.window_configs.get(window_name)
        if config and config.fullscreen:
            self.windows[window_name].showFullScreen()
        else:
            self.windows[window_name].showNormal()
    
    def hide_window(self, window_name: str):
        """Скрыть указанное окно"""
        if window_name in self.windows:
            self.windows[window_name].hide()
    
    def close_window(self, window_name: str):
        """Закрыть указанное окно"""
        if window_name in self.windows:
            self.windows[window_name].close()
            del self.windows[window_name]
    
    def set_fullscreen(self, fullscreen: bool):
        """Установить полноэкранный режим для текущего окна"""
        self.fullscreen = fullscreen
        if self.current_window and self.current_window in self.windows:
            if fullscreen:
                self.windows[self.current_window].showFullScreen()
            else:
                self.windows[self.current_window].showNormal()
    
    def toggle_cursor_visibility(self, visible: bool):
        """Переключение видимости курсора"""
        from PySide6.QtGui import QCursor
        from PySide6.QtCore import Qt
        
        cursor = QCursor(Qt.CursorShape.ArrowCursor) if visible else QCursor(Qt.CursorShape.BlankCursor)
        
        for window in self.windows.values():
            window.setCursor(cursor)
    
    def admin_function(self, access_level: int):
        """Функции администратора"""
        self.access_level = access_level
        for window in self.windows.values():
            if hasattr(window, 'update_access_level'):
                window.update_access_level(access_level)
    
    def close_all_windows(self):
        """Закрыть все окна"""
        for window_name in list(self.windows.keys()):
            self.close_window(window_name)
    
    def run(self):
        """Запуск основного цикла приложения"""
        # Показываем первое окно по умолчанию
        if self.window_configs:
            first_window = next(iter(self.window_configs.keys()))
            if self.window_configs[first_window].show_on_start:
                self.show_window(first_window)
        
        sys.exit(self.app.exec())
