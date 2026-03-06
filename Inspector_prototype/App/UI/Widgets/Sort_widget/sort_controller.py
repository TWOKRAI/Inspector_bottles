# App/UI/Widgets/Sort/sort_controller.py
# -*- coding: utf-8 -*-
"""
SortController — упрощённая версия без WindowManager зависимости.
"""
from typing import Any, Optional, Dict
from PyQt5.QtCore import QObject, pyqtSignal, QTimer

from App.Core.Managers.params_manager import ParamsManager
from App.UI.Widgets.Sort_widget.sort_data import SortData


class SortController(QObject):
    """
    Контроллер для SortWidget.
    
    Сигналы наружу (вместо прямых вызовов):
        recipe_applied: Рецепт применён
        recipe_saved: Рецепт сохранён
        reset_requested: Запрос сброса счётчика (вместо qm.reset_count.set())
    """
    
    # Сигналы вместо прямых вызовов!
    recipe_applied = pyqtSignal(str)   # recipe_id
    recipe_saved = pyqtSignal(str)     # recipe_id
    reset_requested = pyqtSignal()     # Вместо прямого доступа к queue_manager
    
    def __init__(
        self,
        sort_widget,
        sort_data: SortData,
        registers_manager,
        extra_widgets: Optional[Dict[str, Any]] = None,
    ):
        super().__init__()
        
        self._sort_widget = sort_widget
        self._sort_data = sort_data
        self._registers_manager = registers_manager
        
        # ParamsManager
        widgets_dict = {"sort_widget": sort_widget}
        if extra_widgets:
            widgets_dict.update(extra_widgets)
        self._params_manager = ParamsManager(widgets_dict, sort_data)
        
        # Подключаем сигналы от SortWidget
        self._connect_widget_signals()
        
        # Автосохранение
        self._backup_timer = QTimer(self)
        self._backup_timer.timeout.connect(self._auto_save_backup)
        self._backup_timer.start(5000)
        
        # Начальная загрузка
        self._load_initial_recipe()
    
    def _connect_widget_signals(self):
        """Подключаем сигналы от SortWidget."""
        self._sort_widget.applied.connect(self.apply_recipe)
        self._sort_widget.saved.connect(self.save_recipe)
        self._sort_widget.default.connect(self.set_default_recipe)
    
    def _load_initial_recipe(self):
        """Загрузка текущего рецепта при старте."""
        try:
            current = self._sort_data.get_current_recipe_number()
            self._params_manager.apply_recipe(
                current if current is not None else "default_value"
            )
        except Exception as e:
            print(f"[SortController] Ошибка загрузки рецепта: {e}")
    
    def apply_recipe(self, number: Any) -> None:
        """Применить рецепт."""
        self._params_manager.apply_recipe(number)
        
        # Пишем в регистры (вызывает observer → IPC!)
        recipe_data = self._sort_data.get_recipe(str(number))
        self._apply_to_registers(recipe_data)
        
        # Обновляем UI
        if hasattr(self._sort_widget, "refresh_table"):
            self._sort_widget.refresh_table()
        
        # Сигнал наружу вместо прямого действия
        self.recipe_applied.emit(str(number))
    
    def save_recipe(self, number: Any) -> None:
        """Сохранить рецепт."""
        self._params_manager.save_recipe(number)
        
        if hasattr(self._sort_widget, "refresh_table"):
            self._sort_widget.refresh_table()
        
        self.recipe_saved.emit(str(number))
    
    def set_default_recipe(self, number: Any) -> None:
        """Загрузить default_value."""
        self.apply_recipe("default_value")
    
    def reset_count(self) -> None:
        """Сброс счётчика — только сигнал!"""
        self.reset_requested.emit()
    
    def get_all_params(self) -> Dict[str, Any]:
        """Текущие параметры."""
        return self._params_manager.get_all_params()
    
    def _apply_to_registers(self, recipe_data: Dict[str, Any]) -> None:
        """Применение к RegistersManager."""
        for param_name, value in recipe_data.items():
            if "." in param_name:
                register_name, field_name = param_name.split(".", 1)
            else:
                register_name = self._find_register_for_field(param_name)
                field_name = param_name
            
            if register_name and field_name:
                self._registers_manager.set_field_value(register_name, field_name, value)
    
    def _find_register_for_field(self, field_name: str) -> Optional[str]:
        """Маппинг поля на регистр."""
        mapping = {
            "enabled": "camera", "source": "camera", "record_video": "camera",
            "crop_top": "processing", "crop_bottom": "processing",
            "dp": "draw", "minDist": "draw", "param1": "draw", "param2": "draw",
            "servo_on": "robot", "server": "robot",
        }
        return mapping.get(field_name)
    
    def _auto_save_backup(self) -> None:
        """Автосохранение."""
        try:
            self._params_manager.save_to_excel("backup")
        except Exception:
            pass
    
    def cleanup(self) -> None:
        """Остановка таймеров."""
        self._backup_timer.stop()