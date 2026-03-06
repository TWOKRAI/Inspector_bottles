# App/UI/Widgets/Sort/sort_container.py
# -*- coding: utf-8 -*-
"""
SortContainer — обёртка для интеграции SortWidget + SortController в MainWindow.
Минимальная, использует ваши существующие файлы.
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton
from PyQt5.QtCore import pyqtSignal

# Ваши существующие классы
from App.UI.Widgets.Sort_widget.sort_data import SortData
from App.UI.Widgets.Sort_widget.sort_controller import SortController
from App.UI.Widgets.Sort_widget.Sort_widget import SortWidget
from App.UI.Widgets.Sort_widget.sort_excel_export import SortExcelExporter

# Domain
from App.Core.Domain.Registers.manager import RegistersManager
from App.Core.Managers.data_manager import DataManager


class SortContainer(QWidget):
    """
    Контейнер для сортов. Обёртка над вашими существующими классами.
    
    Сигналы наружу:
        recipe_applied, recipe_saved, reset_requested
    """
    
    recipe_applied = pyqtSignal(str)
    recipe_saved = pyqtSignal(str)
    reset_requested = pyqtSignal()
    
    def __init__(
        self,
        registers_manager: RegistersManager,
        data_manager: DataManager,
        parent=None,
    ):
        super().__init__(parent)
        
        # Ваш SortData
        self._sort_data = SortData(
            recipe_manager=data_manager.recipe_manager if data_manager else None
        )
        
        # Ваш SortWidget
        self._sort_widget = SortWidget(
            sort_data=self._sort_data,
            default_number=2,
        )
        
        # Упрощённый SortController (без WindowManager!)
        self._controller = SortController(
            sort_widget=self._sort_widget,
            sort_data=self._sort_data,
            registers_manager=registers_manager,
        )
        
        # Подключаем сигналы контроллера
        self._controller.recipe_applied.connect(self.recipe_applied.emit)
        self._controller.recipe_saved.connect(self.recipe_saved.emit)
        self._controller.reset_requested.connect(self.reset_requested.emit)
        
        # Подключаем сигнал Excel экспорта
        self._sort_widget.export_excel_requested.connect(self._on_export_excel)
        
        # UI
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Ваш SortWidget
        layout.addWidget(self._sort_widget, stretch=1)
        
        # Кнопка сброса (вне SortWidget как у вас было)
        self._reset_btn = QPushButton("Сбросить значения")
        self._reset_btn.setFixedSize(200, 50)
        self._reset_btn.clicked.connect(self._controller.reset_count)
        layout.addWidget(self._reset_btn)
    
    def _on_export_excel(self, path: str):
        """Обработка экспорта (вместо прямого вызова в SortWidget)."""
        success = SortExcelExporter.export_to_excel(self._sort_data, path)
        if success:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, "Экспорт", f"Сохранено: {path}")
        else:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Ошибка", "Не удалось экспортировать")
    
    # Публичный API для MainWindow
    
    def set_params_provider(self, provider):
        """Прокси к SortWidget."""
        self._sort_widget.set_params_provider(provider)
    
    def refresh_table(self):
        """Прокси к SortWidget."""
        self._sort_widget.refresh_table()
    
    def cleanup(self):
        """Остановка таймеров."""
        self._controller.cleanup()
    
    @property
    def current_recipe_id(self):
        return str(self._sort_data.get_current_recipe_number())