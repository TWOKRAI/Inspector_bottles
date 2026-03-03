# -*- coding: utf-8 -*-
"""
Менеджер регионов.
Отвечает только за управление регионами с типизацией через RegionData.
"""
from typing import Optional, List, Dict
from PyQt5.QtCore import QObject, pyqtSignal
from App.Registers import RegionData, ChainStepData
from .camera_manager import CameraManager
from .converter_manager import ConverterManager


class RegionManager(QObject):
    """
    Менеджер регионов.
    Работает с типизированными RegionData моделями через CameraManager.
    """
    
    region_changed = pyqtSignal(str, str)  # camera_id, region_name
    region_added = pyqtSignal(str, str)     # camera_id, region_name
    region_removed = pyqtSignal(str, str)   # camera_id, region_name
    
    def __init__(self, camera_manager: CameraManager, converter: Optional[ConverterManager] = None):
        super().__init__()
        self.camera_manager = camera_manager
        self.converter = converter if converter is not None else ConverterManager()
    
    def get_regions(self, camera_id: Optional[str] = None) -> List[str]:
        """
        Получить список регионов для камеры.
        
        Args:
            camera_id: ID камеры (используется текущая если не указана)
            
        Returns:
            list: Список имён регионов в порядке region_order
        """
        camera = self._get_camera(camera_id)
        if not camera:
            return []
        
        # Возвращаем в порядке region_order
        order = camera.region_order
        if order:
            return [name for name in order if name in camera.regions]
        return list(camera.regions.keys())
    
    def get_region(self, camera_id: Optional[str], region_name: str) -> Optional[RegionData]:
        """
        Получить регион по имени.
        
        Args:
            camera_id: ID камеры (используется текущая если не указана)
            region_name: Имя региона
            
        Returns:
            RegionData: Регион или None если не найден
        """
        camera = self._get_camera(camera_id)
        if not camera:
            return None
        return camera.regions.get(region_name)
    
    def add_region(self, camera_id: Optional[str], region_name: str, 
                   x1: int = 0, y1: int = 0, x2: int = 100, y2: int = 100,
                   enabled: bool = True, is_main: bool = False, 
                   processing_enabled: bool = True) -> bool:
        """
        Добавить регион к камере.
        
        Args:
            camera_id: ID камеры (используется текущая если не указана)
            region_name: Имя региона
            x1, y1, x2, y2: Координаты региона
            enabled: Включен ли регион
            is_main: Является ли регион основным изображением
            processing_enabled: Включена ли обработка
            
        Returns:
            bool: True если регион добавлен
        """
        camera = self._get_camera(camera_id)
        if not camera:
            return False
        
        # Если это основной регион, снимаем флаг is_main с других регионов
        if is_main:
            updated_regions = {}
            for rname, rdata in camera.regions.items():
                updated_regions[rname] = rdata.model_copy(update={"is_main": False})
            camera.regions.update(updated_regions)
        
        # Создаём новый регион
        new_region = RegionData(
            x1=x1, y1=y1, x2=x2, y2=y2,
            enabled=enabled,
            is_main=is_main,
            processing_enabled=processing_enabled,
            chains=[]
        )
        
        # Обновляем камеру
        updated_regions = dict(camera.regions)
        updated_regions[region_name] = new_region
        
        # Обновляем порядок регионов
        updated_order = list(camera.region_order)
        if region_name not in updated_order:
            updated_order.append(region_name)
        
        self.camera_manager.update_camera(
            camera_id or self.camera_manager.get_current_camera_id(),
            regions=updated_regions,
            region_order=updated_order
        )
        
        self.region_added.emit(camera_id or self.camera_manager.get_current_camera_id(), region_name)
        self.region_changed.emit(camera_id or self.camera_manager.get_current_camera_id(), region_name)
        
        return True
    
    def update_region(self, camera_id: Optional[str], region_name: str, **kwargs) -> bool:
        """
        Обновить параметры региона.
        
        Args:
            camera_id: ID камеры (используется текущая если не указана)
            region_name: Имя региона
            **kwargs: Параметры для обновления
            
        Returns:
            bool: True если регион обновлён
        """
        camera = self._get_camera(camera_id)
        if not camera:
            return False
        
        if region_name not in camera.regions:
            return False
        
        region = camera.regions[region_name]
        
        # Если устанавливаем is_main=True, снимаем флаг с других регионов
        if kwargs.get("is_main", False):
            updated_regions = {}
            for rname, rdata in camera.regions.items():
                if rname != region_name:
                    updated_regions[rname] = rdata.model_copy(update={"is_main": False})
                else:
                    updated_regions[rname] = rdata.model_copy(update=kwargs)
            camera.regions.update(updated_regions)
        else:
            # Обновляем только текущий регион
            updated_regions = dict(camera.regions)
            updated_regions[region_name] = region.model_copy(update=kwargs)
            camera.regions.update(updated_regions)
        
        # Обновляем камеру
        self.camera_manager.update_camera(
            camera_id or self.camera_manager.get_current_camera_id(),
            regions=camera.regions
        )
        
        self.region_changed.emit(camera_id or self.camera_manager.get_current_camera_id(), region_name)
        return True
    
    def delete_region(self, camera_id: Optional[str], region_name: str) -> bool:
        """
        Удалить регион.
        
        Args:
            camera_id: ID камеры (используется текущая если не указана)
            region_name: Имя региона
            
        Returns:
            bool: True если регион удалён
        """
        camera = self._get_camera(camera_id)
        if not camera:
            return False
        
        # Нельзя удалить main_image
        if region_name == "main_image":
            return False
        
        if region_name not in camera.regions:
            return False
        
        # Удаляем регион
        updated_regions = dict(camera.regions)
        del updated_regions[region_name]
        
        # Обновляем порядок
        updated_order = list(camera.region_order)
        if region_name in updated_order:
            updated_order.remove(region_name)
        
        self.camera_manager.update_camera(
            camera_id or self.camera_manager.get_current_camera_id(),
            regions=updated_regions,
            region_order=updated_order
        )
        
        self.region_removed.emit(camera_id or self.camera_manager.get_current_camera_id(), region_name)
        return True
    
    def move_region(self, camera_id: Optional[str], region_name: str, direction: int) -> bool:
        """
        Переместить регион вверх (direction=-1) или вниз (direction=1).
        
        Args:
            camera_id: ID камеры (используется текущая если не указана)
            region_name: Имя региона
            direction: Направление перемещения (-1 вверх, 1 вниз)
            
        Returns:
            bool: True если регион перемещён
        """
        camera = self._get_camera(camera_id)
        if not camera:
            return False
        
        order = camera.region_order
        if not order or region_name not in order:
            return False
        
        idx = order.index(region_name)
        new_idx = idx + direction
        
        if new_idx < 0 or new_idx >= len(order):
            return False
        
        # Перемещаем в порядке
        updated_order = list(order)
        updated_order[idx], updated_order[new_idx] = updated_order[new_idx], updated_order[idx]
        
        self.camera_manager.update_camera(
            camera_id or self.camera_manager.get_current_camera_id(),
            region_order=updated_order
        )
        
        self.region_changed.emit(camera_id or self.camera_manager.get_current_camera_id(), region_name)
        return True
    
    def copy_region(self, source_camera_id: Optional[str], source_region_name: str,
                   target_camera_id: Optional[str], target_region_name: Optional[str] = None) -> bool:
        """
        Скопировать регион с одной камеры на другую.
        
        Args:
            source_camera_id: ID исходной камеры
            source_region_name: Имя исходного региона
            target_camera_id: ID целевой камеры
            target_region_name: Имя целевого региона (используется исходное если не указано)
            
        Returns:
            bool: True если регион скопирован
        """
        source_region = self.get_region(source_camera_id, source_region_name)
        if not source_region:
            return False
        
        if target_region_name is None:
            target_region_name = source_region_name
        
        # Создаём копию региона (без is_main)
        new_region = source_region.model_copy(update={"is_main": False})
        
        # Добавляем регион к целевой камере
        target_cam_id = target_camera_id or self.camera_manager.get_current_camera_id()
        camera = self._get_camera(target_cam_id)
        if not camera:
            return False
        
        updated_regions = dict(camera.regions)
        updated_regions[target_region_name] = new_region
        
        updated_order = list(camera.region_order)
        if target_region_name not in updated_order:
            updated_order.append(target_region_name)
        
        self.camera_manager.update_camera(
            target_cam_id,
            regions=updated_regions,
            region_order=updated_order
        )
        
        self.region_added.emit(target_cam_id, target_region_name)
        self.region_changed.emit(target_cam_id, target_region_name)
        
        return True
    
    def get_chains(self, camera_id: Optional[str], region_name: str) -> List[ChainStepData]:
        """
        Получить цепочки обработки для региона.
        
        Args:
            camera_id: ID камеры (используется текущая если не указана)
            region_name: Имя региона
            
        Returns:
            list: Список шагов цепочки
        """
        region = self.get_region(camera_id, region_name)
        if region:
            return region.chains
        return []
    
    def add_chain_step(self, camera_id: Optional[str], region_name: str,
                      processor_id: str, params: Optional[Dict] = None, enabled: bool = True) -> bool:
        """
        Добавить шаг в цепочку обработки региона.
        
        Args:
            camera_id: ID камеры (используется текущая если не указана)
            region_name: Имя региона
            processor_id: ID процессора
            params: Параметры процессора
            enabled: Включен ли шаг
            
        Returns:
            bool: True если шаг добавлен
        """
        region = self.get_region(camera_id, region_name)
        if not region:
            return False
        
        new_step = ChainStepData(
            processor_id=processor_id,
            params=params or {},
            enabled=enabled
        )
        
        updated_chains = list(region.chains)
        updated_chains.append(new_step)
        
        return self.update_region(
            camera_id or self.camera_manager.get_current_camera_id(),
            region_name,
            chains=updated_chains
        )
    
    def update_chain_step(self, camera_id: Optional[str], region_name: str,
                         step_index: int, **kwargs) -> bool:
        """
        Обновить шаг цепочки.
        
        Args:
            camera_id: ID камеры (используется текущая если не указана)
            region_name: Имя региона
            step_index: Индекс шага
            **kwargs: Параметры для обновления
            
        Returns:
            bool: True если шаг обновлён
        """
        region = self.get_region(camera_id, region_name)
        if not region:
            return False
        
        if step_index < 0 or step_index >= len(region.chains):
            return False
        
        updated_chains = list(region.chains)
        updated_chains[step_index] = updated_chains[step_index].model_copy(update=kwargs)
        
        return self.update_region(
            camera_id or self.camera_manager.get_current_camera_id(),
            region_name,
            chains=updated_chains
        )
    
    def delete_chain_step(self, camera_id: Optional[str], region_name: str, step_index: int) -> bool:
        """
        Удалить шаг из цепочки.
        
        Args:
            camera_id: ID камеры (используется текущая если не указана)
            region_name: Имя региона
            step_index: Индекс шага
            
        Returns:
            bool: True если шаг удалён
        """
        region = self.get_region(camera_id, region_name)
        if not region:
            return False
        
        if step_index < 0 or step_index >= len(region.chains):
            return False
        
        updated_chains = list(region.chains)
        updated_chains.pop(step_index)
        
        return self.update_region(
            camera_id or self.camera_manager.get_current_camera_id(),
            region_name,
            chains=updated_chains
        )
    
    def move_chain_step(self, camera_id: Optional[str], region_name: str,
                       step_index: int, direction: int) -> bool:
        """
        Переместить шаг цепочки вверх (direction=-1) или вниз (direction=1).
        
        Args:
            camera_id: ID камеры (используется текущая если не указана)
            region_name: Имя региона
            step_index: Индекс шага
            direction: Направление перемещения
            
        Returns:
            bool: True если шаг перемещён
        """
        region = self.get_region(camera_id, region_name)
        if not region:
            return False
        
        if step_index < 0 or step_index >= len(region.chains):
            return False
        
        new_idx = step_index + direction
        if new_idx < 0 or new_idx >= len(region.chains):
            return False
        
        updated_chains = list(region.chains)
        updated_chains[step_index], updated_chains[new_idx] = updated_chains[new_idx], updated_chains[step_index]
        
        return self.update_region(
            camera_id or self.camera_manager.get_current_camera_id(),
            region_name,
            chains=updated_chains
        )
    
    def _get_camera(self, camera_id: Optional[str]):
        """Вспомогательный метод для получения камеры"""
        if camera_id:
            return self.camera_manager.get_camera(camera_id)
        return self.camera_manager.get_current_camera()
