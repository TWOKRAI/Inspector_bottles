# App/UI/Windows/main_window.py
# -*- coding: utf-8 -*-
"""
MainWindow — главное окно приложения.

Ответственность:
  - Компоновка виджетов (Header + ImagePanel + Tabs)
  - Проксирование сигналов между виджетами и наружу (к WindowManager)
  - Применение глобальных настроек (access_level, но не бизнес-логика!)

НЕ делает:
  - Не создаёт менеджеры (получает в __init__)
  - Не управляет потоками (только принимает сигналы от них)
  - Не шлёт IPC команды (только сигналы наружу)
  - Не хранит FPS-метрики (они в ImagePanel)

Архитектура:
  MainWindow (QMainWindow)
    ├── HeaderWidget (общий компонент)
    ├── ImagePanelWidget (отображение + метрики)
    └── TabWidget
        ├── SortContainer (автономный)
        ├── VisualConfigWidget
        ├── LoggingWidget
        ├── HikvisionWidget (автономный)
        ├── PostProcessingWidget
        ├── ProcessingWidget
        └── CircleWidget
"""

from typing import Optional, List, Any
import numpy as np

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QScrollArea, QTabWidget
)

# Components
from App.UI.Components.header import HeaderWidget
from App.UI.Components.tab_widget import TabWidget, BaseTab

# Widgets
from App.UI.Widgets.ImagePanel_widget.image_panel import ImagePanelWidget
from App.UI.Widgets.Hikvision_widget.Hikvision import HikvisionWidget  
from App.UI.Widgets.Sort_widget.sort_container import SortContainer
from App.UI.Widgets.Visual_config_widget.visual_config import VisualConfigWidget
from App.UI.Widgets.Logging_widget.logging_widget import LoggingWidget
from App.UI.Widgets.PostProcessing_widget.post_processing import PostProcessingWidget
from App.UI.Widgets.Processing_widget.processing import ProcessingWidget
from App.UI.Widgets.Circle_widget.circle_widget import CircleWidget

# Config & Domain (только для инжекции в дочерние виджеты)
from App.Core.Config.app_config import AppConfig
from App.Core.Domain.Registers.manager import RegistersManager
from App.Core.Managers.data_manager import DataManager


class MainWindow(QMainWindow):
    """
    Главное окно — чистый compositor.
    
    Сигналы наружу (для WindowManager):
        reset_count_requested: Пользователь нажал "Сбросить счётчик"
        recipe_apply_requested: Пользователь хочет применить рецепт (id)
        recipe_save_requested: Пользователь хочет сохранить рецепт (id)
        access_level_changed: Изменился уровень доступа (прокси от виджетов)
    """
    
    # Сигналы для WindowManager
    reset_count_requested = pyqtSignal()
    recipe_apply_requested = pyqtSignal(str)   # recipe_id
    recipe_save_requested = pyqtSignal(str)    # recipe_id
    
    # Внутренние сигналы (между виджетами, но через MainWindow как hub)
    # Hikvision → ImagePanel (размер, FPS)
    # ImagePanel → Sort (текущие параметры для отображения)
    
    def __init__(
        self,
        registers_manager: RegistersManager,
        data_manager: DataManager,
        config: AppConfig,
        parent=None,
    ):
        super().__init__(parent)
        
        # Сохраняем зависимости (только для передачи в дочерние виджеты)
        self._registers = registers_manager
        self._data = data_manager
        self._config = config
        
        # Runtime state (минимальный!)
        self._current_access_level: int = 0
        
        # Создаём UI
        self._init_ui()
        
        # Подключаем межвиджетные сигналы
        self._connect_inter_widget_signals()
    
    # ═════════════════════════════════════════════════════════════════
    # UI Construction (только компоновка!)
    # ═════════════════════════════════════════════════════════════════
    
    def _init_ui(self) -> None:
        """Сборка UI из виджетов."""
        self.setWindowTitle("Inspector")
        self.setMinimumSize(
            self._config.window.window_min_width,
            self._config.window.window_min_height
        )
        
        # Центральный виджет
        central = QWidget()
        self.setCentralWidget(central)
        
        # Главный layout: вертикальный
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        
        # 1. Header (общий компонент)
        self.header = HeaderWidget()  # Публичный для подключения сигналов в WindowManager
        layout.addWidget(self.header)
        
        # 2. Image Panel (отображение + метрики)
        self.image_panel = ImagePanelWidget(
            registers_manager=self._registers,
            parent=self,
        )
        layout.addWidget(self.image_panel, stretch=1)  # Растягивается
        
        # 3. Tabs (нижняя панель)
        self.tabs = self._create_tabs()
        layout.addWidget(self.tabs)
    
    def _create_tabs(self) -> TabWidget:
        """Создание вкладок с виджетами."""
        tabs = TabWidget()
        
        # ── 1. Сорта (автономный контейнер) ──
        self.sort_container = SortContainer(
            registers_manager=self._registers,
            data_manager=self._data,
        )
        # Подключаем сигналы от SortContainer
        self.sort_container.reset_requested.connect(self.reset_count_requested.emit)
        self.sort_container.recipe_applied.connect(self.recipe_apply_requested.emit)
        self.sort_container.recipe_saved.connect(self.recipe_save_requested.emit)
        
        tabs.add_tab(self.sort_container, "Сорта", wrap_scroll=False)
        
        # ── 2. Визуальная настройка ──
        self.visual_config = VisualConfigWidget(
            registers_manager=self._registers,
            config=self._config,
        )
        tabs.add_tab(self.visual_config, "Визуальная настройка")
        
        # ── 3. Логирование ──
        self.logging_widget = LoggingWidget(
            data_manager=self._data,
        )
        tabs.add_tab(self.logging_widget, "Логирование")
        
        # ── 4. Hikvision (автономный) ──
        self.hikvision_widget = HikvisionWidget(
            registers_manager=self._registers,
            data_manager=self._data,
            # CameraService получает через DataManager или отдельно
        )
        # Сигналы от Hikvision будут подключены в _connect_inter_widget_signals
        tabs.add_tab(self.hikvision_widget, "Hikvision")
        
        # ── 5. Регионы (PostProcessing) ──
        self.post_processing = PostProcessingWidget(
            registers_manager=self._registers,
            data_manager=self._data,
        )
        tabs.add_tab(self.post_processing, "Регионы")
        
        # ── 6. Обработка (Processing) ──
        self.processing_widget = ProcessingWidget(
            registers_manager=self._registers,
            data_manager=self._data,
        )
        tabs.add_tab(self.processing_widget, "Обработка")
        
        # ── 7. Форма (Circle) ──
        self.circle_widget = CircleWidget(
            registers_manager=self._registers,
        )
        tabs.add_tab(self.circle_widget, "Форма")
        
        return tabs
    
    # ═════════════════════════════════════════════════════════════════
    # Межвиджетные связи (через MainWindow как hub)
    # ═════════════════════════════════════════════════════════════════
    
    def _connect_inter_widget_signals(self) -> None:
        """
        Подключение сигналов между виджетами.
        MainWindow выступает как маршрутизатор, но не обрабатывает данные!
        """
        
        # Hikvision → ImagePanel (размер изображения)
        self.hikvision_widget.image_size_detected.connect(
            self.image_panel.update_image_size
        )
        
        # Hikvision → ImagePanel (FPS от камеры)
        self.hikvision_widget.parameters_changed.connect(
            self._on_camera_params_changed
        )
        
        # SortContainer → ImagePanel (запрос текущих параметров для отображения)
        # ImagePanel не хранит параметры, но может запросить отображение метрик
        # self.sort_container.params_requested.connect(...)
    
    def _on_camera_params_changed(self, params: dict) -> None:
        """
        Прокси: Hikvision → ImagePanel (FPS и другие параметры камеры).
        Можно добавить фильтрацию или преобразование здесь.
        """
        # Пробрасываем в ImagePanel
        self.image_panel.update_camera_params(params)
        
        # Или конкретные поля:
        # fps = params.get('frame_rate', 0.0)
        # self.image_panel.update_camera_fps(fps)
    
    # ═════════════════════════════════════════════════════════════════
    # Публичный API: входящие сигналы (от ThreadManager / WindowManager)
    # ═════════════════════════════════════════════════════════════════
    
    def display_frame(self, frames: List[np.ndarray], metrics: Optional[dict] = None) -> None:
        """
        Slot от UpdateImage thread (через WindowManager).
        
        Args:
            frames: Список кадров (обычно 1)
            metrics: Опциональные метрики (FPS, время обработки, etc)
        """
        self.image_panel.display_frame(frames, metrics)
    
    def update_access_level(self, level: int) -> None:
        """
        Установить уровень доступа (вызывается из WindowManager).
        Распространяет на все ConfigurableWidget в иерархии.
        """
        self._current_access_level = level
        
        # Рекурсивно находим все ConfigurableWidget
        from App.Core.base_configurable_widget import ConfigurableWidget
        
        for widget in self.findChildren(ConfigurableWidget):
            widget.access_level = level
        
        # Сигнал для внешних подписчиков
        # self.access_level_changed.emit(level)
    
    # ═════════════════════════════════════════════════════════════════
    # Cleanup
    # ═════════════════════════════════════════════════════════════════
    
    def closeEvent(self, event) -> None:
        """Graceful cleanup при закрытии окна."""
        # Уведомляем автономные виджеты о необходимости cleanup
        if hasattr(self.hikvision_widget, 'cleanup'):
            self.hikvision_widget.cleanup()
        
        if hasattr(self.sort_container, 'cleanup'):
            self.sort_container.cleanup()
        
        # Принимаем закрытие
        event.accept()
    
    # ═════════════════════════════════════════════════════════════════
    # Properties (для доступа WindowManager, но минимальные!)
    # ═════════════════════════════════════════════════════════════════
    
    @property
    def current_access_level(self) -> int:
        return self._current_access_level
    
    # НЕТ свойств типа fps, image_width и т.д. — они в ImagePanel!