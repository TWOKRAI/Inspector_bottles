# App/Core/Application/window_manager.py
# -*- coding: utf-8 -*-
"""
WindowManager — управление жизненным циклом окон.

Ответственность:
  - Реестр окон (создание, хранение, доступ)
  - Показ/скрытие/закрытие окон
  - Глобальные операции с окнами (fullscreen, cursor, access_level)

НЕ делает:
  - Не создаёт потоки (ThreadManager)
  - Не управляет IPC (RouterManager)
  - Не знает про бизнес-логику (только проксирует сигналы)

Архитектура:
  WindowManager
    └── WindowRegistry (фабрика и хранение)
        └── WindowEntry (конфигурация окна)
"""

from typing import Optional
from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import QObject, pyqtSignal, Qt
from PyQt5.QtGui import QCursor

# Config
from App.Core.Config.app_config import AppConfig

# Application
from App.Core.Application.window_registry import WindowRegistry

# Domain (только для инжекции в окна)
from App.Core.Domain.Registers.manager import RegistersManager
from App.Core.Managers.data_manager import DataManager



# ═════════════════════════════════════════════════════════════════════
# Window Manager — публичный API для Coordinator
# ═════════════════════════════════════════════════════════════════════

class WindowManager(QObject):
    """
    Управление окнами приложения.
    
    Сигналы наружу (для Coordinator):
        reset_count_requested: Запрос сброса счётчика
        recipe_apply_requested: Запрос применения рецепта
        window_shown: Окно показано (имя)
        window_hidden: Окно скрыто (имя)
    """
    
    # Сигналы для Coordinator
    reset_count_requested = pyqtSignal()
    recipe_apply_requested = pyqtSignal(str)  # recipe_id
    recipe_save_requested = pyqtSignal(str)     # recipe_id
    
    window_shown = pyqtSignal(str)   # window_name
    window_hidden = pyqtSignal(str)  # window_name
    
    def __init__(
        self,
        config: AppConfig,
        registers_manager: RegistersManager,
        data_manager: DataManager,
        parent=None,
    ):
        super().__init__(parent)
        
        # Зависимости (только для инжекции в окна)
        self._config = config
        self._registers = registers_manager
        self._data_manager = data_manager
        
        # Реестр окон
        self._registry = WindowRegistry()
        self._setup_windows()
        
        # State
        self._current_window: Optional[str] = None
        self._access_level: int = 0
    
    # ═════════════════════════════════════════════════════════════════
    # Регистрация окон (единое место конфигурации!)
    # ═════════════════════════════════════════════════════════════════
    
    def _setup_windows(self) -> None:
        """
        Регистрация ВСЕХ окон приложения.
        Единственное место, где добавляются новые окна!
        """
        
        # === Main Window ===
        self._registry.register(
            "main",
            factory=self._create_main_window,
            singleton=True,
            needs_fullscreen=True,
            needs_cursor=True,
            needs_access_level=True,
        )
        
        # === Loading Window ===
        self._registry.register(
            "loading",
            factory=self._create_loading_window,
            singleton=True,
            needs_fullscreen=True,  # Как main при старте
            needs_cursor=True,
            needs_access_level=False,  # Нет админских контролов
        )
        
        # === Neuroun Window ===
        self._registry.register(
            "neuroun",
            factory=self._create_neuroun_window,
            singleton=True,
            needs_fullscreen=True,
            needs_cursor=True,
            needs_access_level=True,
        )
        
        # === Message Window ===
        self._registry.register(
            "message",
            factory=self._create_message_window,
            singleton=False,  # Можно много сообщений
            needs_fullscreen=False,
            needs_cursor=True,
            needs_access_level=False,
            auto_close=10,  # Автозакрытие через 10 сек
        )
    
    # ═════════════════════════════════════════════════════════════════
    # Factory methods (каждая создаёт своё окно)
    # ═════════════════════════════════════════════════════════════════
    
    def _create_main_window(self) -> QWidget:
        """Фабрика MainWindow."""
        # Ленивый импорт чтобы избежать циклов
        from App.UI.Windows.main_window import MainWindow
        
        window = MainWindow(
            registers_manager=self._registers,
            data_manager=self._data_manager,
            config=self._config,
        )
        
        # Подключаем сигналы от MainWindow
        window.reset_count_requested.connect(self.reset_count_requested.emit)
        window.recipe_apply_requested.connect(self.recipe_apply_requested.emit)
        window.recipe_save_requested.connect(self.recipe_save_requested.emit)
        
        # Header сигналы (переключение окон)
        window.header.main_show.connect(self.show_main_window)
        window.header.neuroun_show.connect(self.show_neuroun_window)
        
        return window
    
    def _create_loading_window(self) -> QWidget:
        """Фабрика LoadingWindow."""
        from App.UI.Windows.loading_window import LoadingWindow
        
        # LoadingWindow показывается в той же геометрии, что и main
        main_geom = self._get_main_geometry()
        
        window = LoadingWindow(
            target_geometry=main_geom,
        )
        
        return window
    
    def _create_neuroun_window(self) -> QWidget:
        """Фабрика NeurounWindow."""
        from App.UI.Windows.neuroun_window import NeurounWindow
        
        window = NeurounWindow(
            registers_manager=self._registers,
        )
        
        # Header сигналы
        window.header.main_show.connect(self.show_main_window)
        window.header.neuroun_show.connect(self.show_neuroun_window)
        
        return window
    
    def _create_message_window(self, message: str = "") -> QWidget:
        """Фабрика MessageWindow (не singleton!)."""
        from App.UI.Windows.message_window import MessageWindow
        
        window = MessageWindow(message=message)
        
        # Автозакрытие настроено в Entry, здесь не нужно
        
        return window
    
    def _get_main_geometry(self):
        """Получить геометрию для окон (до создания main!)."""
        from PyQt5.QtCore import QRect
        return QRect(100, 100, 1200, 800)
    
    # ═════════════════════════════════════════════════════════════════
    # Публичный API: управление окнами
    # ═════════════════════════════════════════════════════════════════
    
    def show_initial_window(self) -> None:
        """Показать начальное окно (loading или main)."""
        # Создаём loading и main
        self._registry.create("loading")
        self._registry.create("main")
        
        # Показываем loading
        self._show("loading")
        self._current_window = "loading"
    
    def show_main_window(self) -> None:
        """Показать главное окно, скрыть остальные."""
        self._hide("neuroun")
        self._show("main")
        self._current_window = "main"
        self.window_shown.emit("main")
    
    def show_neuroun_window(self) -> None:
        """Показать окно нейросети."""
        # Создаём если ещё нет (singleton)
        if not self._registry.is_created("neuroun"):
            self._registry.create("neuroun")
        
        self._hide("main")
        self._show("neuroun")
        self._current_window = "neuroun"
        self.window_shown.emit("neuroun")
    
    def show_message(self, message: str) -> None:
        """Показать сообщение (не singleton — создаём каждый раз)."""
        # Для message создаём новый инстанс каждый раз
        window = self._registry.create("message", message=message)
        if window:
            window.show()
            window.raise_()
    
    def get_window(self, name: str) -> Optional[QWidget]:
        """Получить окно по имени (или None если не создано)."""
        return self._registry.get(name)
    
    def get_current_window_name(self) -> Optional[str]:
        """Имя текущего видимого окна."""
        return self._current_window
    
    def close_all(self) -> None:
        """Закрыть все окна."""
        self._registry.close_all()
        self._current_window = None
    
    # ═════════════════════════════════════════════════════════════════
    # Глобальные операции (применяются к нескольким окнам)
    # ═════════════════════════════════════════════════════════════════
    
    def set_fullscreen(self, fullscreen: bool) -> None:
        """
        Установить fullscreen для всех окон, которые это поддерживают.
        """
        # Получаем ограничения из конфига
        limit = self._config.window.limit_fullscreen_resolution
        max_w = self._config.window.fullscreen_max_width
        max_h = self._config.window.fullscreen_max_height
        
        def apply(window: QWidget):
            if fullscreen:
                if limit:
                    # Оконный режим с фиксированным размером
                    window.showNormal()
                    window.setFixedSize(max_w, max_h)
                    screen = window.screen().availableGeometry()
                    x = (screen.width() - max_w) // 2
                    y = (screen.height() - max_h) // 2
                    window.move(x, y)
                else:
                    # Настоящий fullscreen
                    window.showFullScreen()
            else:
                # Обычный режим
                window.setFixedSize(16777215, 16777215)
                window.setMaximumSize(16777215, 16777215)
                window.setMinimumSize(
                    self._config.window.window_min_width,
                    self._config.window.window_min_height,
                )
                window.showNormal()
        
        # Применяем только к окнам с needs_fullscreen=True
        names = self._registry.filter_names(needs_fullscreen=True, created_only=True)
        self._registry.apply(names, apply)
    
    def toggle_cursor(self, visible: bool) -> None:
        """Показать/скрыть курсор в окнах."""
        cursor = QCursor(Qt.ArrowCursor) if visible else QCursor(Qt.BlankCursor)
        
        names = self._registry.filter_names(needs_cursor=True, created_only=True)
        self._registry.apply(names, lambda w: w.setCursor(cursor))
    
    def set_access_level(self, level: int) -> None:
        """Установить уровень доступа во все окна."""
        self._access_level = level
        
        def apply(window: QWidget):
            if hasattr(window, 'update_access_level'):
                window.update_access_level(level)
        
        names = self._registry.filter_names(needs_access_level=True, created_only=True)
        self._registry.apply(names, apply)
    
    # ═════════════════════════════════════════════════════════════════
    # Private helpers
    # ═════════════════════════════════════════════════════════════════
    
    def _show(self, name: str) -> None:
        """Показать окно по имени."""
        window = self._registry.get(name)
        if window:
            window.show()
            window.raise_()
            window.activateWindow()
    
    def _hide(self, name: str) -> None:
        """Скрыть окно по имени."""
        window = self._registry.get(name)
        if window:
            window.hide()
            self.window_hidden.emit(name)