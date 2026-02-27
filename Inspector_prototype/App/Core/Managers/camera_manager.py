# -*- coding: utf-8 -*-
"""
Менеджер камер.
Отвечает только за управление камерами с типизацией через CameraData.
"""
from typing import Dict, Optional, List
from PyQt5.QtCore import QObject, pyqtSignal
from App.Registers.models.field_data import CameraData
from .converter_manager import ConverterManager


class CameraManager(QObject):
    """
    Менеджер камер.
    Работает с типизированными CameraData моделями.
    """
    
    camera_changed = pyqtSignal(str)  # camera_id
    camera_added = pyqtSignal(str)    # camera_id
    camera_removed = pyqtSignal(str)  # camera_id
    
    def __init__(self, converter: Optional[ConverterManager] = None):
        super().__init__()
        self.converter = converter if converter is not None else ConverterManager()
        self._cameras: Dict[str, CameraData] = {}
        self._current_camera_id: Optional[str] = None
    
    def add_camera(self, camera_id: Optional[str] = None, name: Optional[str] = None) -> Optional[CameraData]:
        """
        Добавить новую камеру.
        
        Args:
            camera_id: ID камеры (генерируется автоматически если не указан)
            name: Название камеры
            
        Returns:
            CameraData: Созданная камера или None если камера уже существует
        """
        if camera_id is None:
            camera_id = f"camera_{len(self._cameras)}"
        
        if camera_id in self._cameras:
            return None
        
        # Создаём камеру с дефолтными значениями
        camera = CameraData(
            name=name or f"Camera {len(self._cameras) + 1}",
            hikvision_params={
                "Frame Rate": 0.0,
                "Exposure": 0,
                "Gain": 0.0
            },
            region_order=["main_image"],
            regions={
                "main_image": self._create_default_main_region()
            }
        )
        
        self._cameras[camera_id] = camera
        self.camera_added.emit(camera_id)
        self.camera_changed.emit(camera_id)
        
        return camera
    
    def _create_default_main_region(self):
        """Создать регион основного изображения по умолчанию"""
        from App.Registers.models.field_data import RegionData
        return RegionData(
            x1=0, y1=0, x2=3840, y2=2160,
            enabled=True,
            is_main=True,
            processing_enabled=True,
            chains=[]
        )
    
    def get_camera(self, camera_id: str) -> Optional[CameraData]:
        """
        Получить камеру по ID.
        
        Args:
            camera_id: ID камеры
            
        Returns:
            CameraData: Камера или None если не найдена
        """
        return self._cameras.get(camera_id)
    
    def get_cameras(self) -> List[str]:
        """Получить список ID всех камер."""
        return list(self._cameras.keys())
    
    def update_camera(self, camera_id: str, **kwargs) -> bool:
        """
        Обновить параметры камеры.
        
        Args:
            camera_id: ID камеры
            **kwargs: Параметры для обновления
            
        Returns:
            bool: True если камера обновлена
        """
        if camera_id not in self._cameras:
            return False
        
        camera = self._cameras[camera_id]
        
        # Обновляем поля через model_copy
        update_data = camera.model_dump()
        update_data.update(kwargs)
        
        try:
            self._cameras[camera_id] = CameraData.model_validate(update_data)
            self.camera_changed.emit(camera_id)
            return True
        except Exception as e:
            print(f"Ошибка обновления камеры {camera_id}: {e}")
            return False
    
    def remove_camera(self, camera_id: str) -> bool:
        """
        Удалить камеру.
        
        Args:
            camera_id: ID камеры
            
        Returns:
            bool: True если камера удалена
        """
        if camera_id not in self._cameras:
            return False
        
        del self._cameras[camera_id]
        
        if self._current_camera_id == camera_id:
            self._current_camera_id = None
        
        self.camera_removed.emit(camera_id)
        return True
    
    def set_current_camera(self, camera_id: Optional[str]):
        """
        Установить текущую камеру.
        
        Args:
            camera_id: ID камеры или None для сброса
        """
        if camera_id is None:
            self._current_camera_id = None
            return
        
        if camera_id in self._cameras:
            self._current_camera_id = camera_id
            self.camera_changed.emit(camera_id)
    
    def get_current_camera_id(self) -> Optional[str]:
        """
        Получить ID текущей камеры.
        
        Returns:
            str: ID текущей камеры или первая доступная, или None
        """
        if self._current_camera_id and self._current_camera_id in self._cameras:
            return self._current_camera_id
        
        cameras = self.get_cameras()
        if cameras:
            return cameras[0]
        
        return None
    
    def get_current_camera(self) -> Optional[CameraData]:
        """Получить текущую камеру."""
        camera_id = self.get_current_camera_id()
        if camera_id:
            return self.get_camera(camera_id)
        return None
    
    def set_hikvision_params(self, camera_id: str, params: Dict[str, float]) -> bool:
        """
        Установить параметры Hikvision для камеры.
        
        Args:
            camera_id: ID камеры
            params: Словарь параметров
            
        Returns:
            bool: True если параметры установлены
        """
        return self.update_camera(camera_id, hikvision_params=params)
    
    def get_hikvision_params(self, camera_id: str) -> Dict[str, float]:
        """
        Получить параметры Hikvision для камеры.
        
        Args:
            camera_id: ID камеры
            
        Returns:
            dict: Параметры Hikvision или пустой словарь
        """
        camera = self.get_camera(camera_id)
        if camera:
            return camera.hikvision_params
        return {}
    
    def model_dump_all(self) -> Dict[str, Dict[str, any]]:
        """
        Экспорт всех камер в словарь для сохранения.
        
        Returns:
            dict: Словарь {camera_id: camera_dict}
        """
        return {
            camera_id: self.converter.to_dict(camera)
            for camera_id, camera in self._cameras.items()
        }
    
    def model_validate_all(self, data: Dict[str, Dict[str, any]]):
        """
        Загрузить все камеры из словаря с валидацией.
        
        Args:
            data: Словарь {camera_id: camera_dict}
        """
        self._cameras = {}
        for camera_id, camera_dict in data.items():
            try:
                self._cameras[camera_id] = CameraData.model_validate(camera_dict)
            except Exception as e:
                print(f"Ошибка валидации камеры {camera_id}: {e}")
