# -*- coding: utf-8 -*-
"""
Упрощённый DataManager - координатор всех менеджеров данных.
Объединяет CameraManager, RegionManager и RecipeManager в единый интерфейс.
"""
from typing import Optional
from PyQt5.QtCore import QObject, pyqtSignal
from .camera_manager import CameraManager
from .region_manager import RegionManager
from .recipe_manager import RecipeManager
from .converter_manager import ConverterManager


class DataManager(QObject):
    """
    Координатор всех менеджеров данных.
    Предоставляет единый интерфейс для виджетов, сохраняя обратную совместимость.
    """
    
    # Сигналы для обратной совместимости
    camera_changed = pyqtSignal(str)  # camera_id
    region_changed = pyqtSignal(str, str)  # camera_id, region_name
    chain_changed = pyqtSignal(str, str)  # camera_id, region_name
    data_changed = pyqtSignal()  # Общее изменение данных
    
    def __init__(self, recipe_manager: Optional[RecipeManager] = None,
                 converter: Optional[ConverterManager] = None):
        super().__init__()
        
        # Создаём менеджеры
        self.converter = converter if converter is not None else ConverterManager()
        self.recipe_manager = recipe_manager if recipe_manager is not None else RecipeManager(converter=self.converter)
        self.camera_manager = CameraManager(converter=self.converter)
        self.region_manager = RegionManager(self.camera_manager, converter=self.converter)
        
        # Подключаем сигналы для проброса
        self.camera_manager.camera_changed.connect(self._on_camera_changed)
        self.camera_manager.camera_added.connect(self._on_camera_added)
        self.camera_manager.camera_removed.connect(self._on_camera_removed)
        self.region_manager.region_changed.connect(self._on_region_changed)
        self.region_manager.region_added.connect(self._on_region_added)
        self.region_manager.region_removed.connect(self._on_region_removed)
        
        # Загружаем данные из текущего рецепта
        self._load_from_recipe()
    
    def _load_from_recipe(self):
        """Загрузить данные из текущего рецепта"""
        try:
            current_recipe = self.recipe_manager.get_current_recipe_number()
            recipe_data = self.recipe_manager.load_structured_recipe(current_recipe)
            
            # Загружаем данные камер если есть
            if "cameras" in recipe_data:
                cameras_data = recipe_data["cameras"]
                if isinstance(cameras_data, dict):
                    self.camera_manager.model_validate_all(cameras_data)
        except Exception as e:
            print(f"Ошибка загрузки данных из рецепта: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_camera_changed(self, camera_id: str):
        """Обработчик изменения камеры"""
        self.camera_changed.emit(camera_id)
        self.data_changed.emit()
    
    def _on_camera_added(self, camera_id: str):
        """Обработчик добавления камеры"""
        self.camera_changed.emit(camera_id)
        self.data_changed.emit()
    
    def _on_camera_removed(self, camera_id: str):
        """Обработчик удаления камеры"""
        self.camera_changed.emit(camera_id)
        self.data_changed.emit()
    
    def _on_region_changed(self, camera_id: str, region_name: str):
        """Обработчик изменения региона"""
        self.region_changed.emit(camera_id, region_name)
        self.data_changed.emit()
    
    def _on_region_added(self, camera_id: str, region_name: str):
        """Обработчик добавления региона"""
        self.region_changed.emit(camera_id, region_name)
        self.data_changed.emit()
    
    def _on_region_removed(self, camera_id: str, region_name: str):
        """Обработчик удаления региона"""
        self.region_changed.emit(camera_id, region_name)
        self.data_changed.emit()
    
    # Методы для обратной совместимости со старым DataManager
    
    def get_cameras(self):
        """Получить список всех камер (обратная совместимость)"""
        return self.camera_manager.get_cameras()
    
    def get_camera(self, camera_id):
        """Получить данные камеры (обратная совместимость)"""
        camera = self.camera_manager.get_camera(camera_id)
        if camera:
            return self.converter.to_dict(camera)
        return {}
    
    def add_camera(self, camera_id=None, name=None):
        """Добавить новую камеру (обратная совместимость)"""
        camera = self.camera_manager.add_camera(camera_id, name)
        if camera:
            return camera_id or f"camera_{len(self.camera_manager.get_cameras()) - 1}"
        return None
    
    def set_current_camera(self, camera_id):
        """Установить текущую камеру (обратная совместимость)"""
        self.camera_manager.set_current_camera(camera_id)
    
    def get_current_camera_id(self):
        """Получить ID текущей камеры (обратная совместимость)"""
        return self.camera_manager.get_current_camera_id()
    
    def get_regions(self, camera_id=None):
        """Получить список регионов для камеры (обратная совместимость)"""
        return self.region_manager.get_regions(camera_id)
    
    def get_region(self, camera_id, region_name):
        """Получить данные региона (обратная совместимость)"""
        region = self.region_manager.get_region(camera_id, region_name)
        if region:
            return self.converter.to_dict(region)
        return {}
    
    def add_region(self, camera_id, region_name, x1=0, y1=0, x2=100, y2=100,
                   enabled=True, is_main=False, processing_enabled=True):
        """Добавить регион к камере (обратная совместимость)"""
        return self.region_manager.add_region(
            camera_id, region_name, x1, y1, x2, y2,
            enabled, is_main, processing_enabled
        )
    
    def update_region(self, camera_id, region_name, **kwargs):
        """Обновить параметры региона (обратная совместимость)"""
        return self.region_manager.update_region(camera_id, region_name, **kwargs)
    
    def delete_region(self, camera_id, region_name):
        """Удалить регион (обратная совместимость)"""
        return self.region_manager.delete_region(camera_id, region_name)
    
    def move_region(self, camera_id, region_name, direction):
        """Переместить регион (обратная совместимость)"""
        return self.region_manager.move_region(camera_id, region_name, direction)
    
    def copy_region(self, source_camera_id, source_region_name, target_camera_id, target_region_name=None):
        """Скопировать регион (обратная совместимость)"""
        return self.region_manager.copy_region(
            source_camera_id, source_region_name,
            target_camera_id, target_region_name
        )
    
    def get_chains(self, camera_id, region_name):
        """Получить цепочки обработки для региона (обратная совместимость)"""
        chains = self.region_manager.get_chains(camera_id, region_name)
        return [self.converter.to_dict(chain) for chain in chains]
    
    def add_chain_step(self, camera_id, region_name, processor_id, params=None, enabled=True):
        """Добавить шаг в цепочку обработки региона (обратная совместимость)"""
        return self.region_manager.add_chain_step(camera_id, region_name, processor_id, params, enabled)
    
    def update_chain_step(self, camera_id, region_name, step_index, **kwargs):
        """Обновить шаг цепочки (обратная совместимость)"""
        return self.region_manager.update_chain_step(camera_id, region_name, step_index, **kwargs)
    
    def delete_chain_step(self, camera_id, region_name, step_index):
        """Удалить шаг из цепочки (обратная совместимость)"""
        return self.region_manager.delete_chain_step(camera_id, region_name, step_index)
    
    def move_chain_step(self, camera_id, region_name, step_index, direction):
        """Переместить шаг цепочки (обратная совместимость)"""
        return self.region_manager.move_chain_step(camera_id, region_name, step_index, direction)
    
    def set_camera_hikvision_params(self, camera_id, params):
        """Установить параметры Hikvision для камеры (обратная совместимость)"""
        return self.camera_manager.set_hikvision_params(camera_id, params)
    
    def get_camera_hikvision_params(self, camera_id):
        """Получить параметры Hikvision для камеры (обратная совместимость)"""
        return self.camera_manager.get_hikvision_params(camera_id)
    
    def save_to_recipe(self, recipe_id="backup"):
        """
        Сохранить текущие данные в рецепт.
        
        Args:
            recipe_id: ID рецепта (по умолчанию "backup")
        """
        try:
            # Экспортируем данные камер
            cameras_data = self.camera_manager.model_dump_all()
            
            # Сохраняем через RecipeManager
            # Для полного сохранения нужно также передать регистры, но это делается отдельно
            # через ParamsManager или напрямую
            self.recipe_manager.save_structured_recipe(recipe_id, {}, cameras_data)
            
            self.data_changed.emit()
        except Exception as e:
            print(f"Ошибка сохранения данных в рецепт {recipe_id}: {e}")
            import traceback
            traceback.print_exc()
