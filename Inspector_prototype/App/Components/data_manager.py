# -*- coding: utf-8 -*-
"""
Менеджер данных для многоуровневой структуры:
Уровень 0: Рецепты
Уровень 1: Камеры
Уровень 2: Регионы (включая основное изображение)
Уровень 3: Цепочки обработки
Уровень 4: Параметры обработки
"""
import json
from PyQt5.QtCore import QObject, pyqtSignal
from App.Widget.Sort_widjet.sort_data import SortData


class DataManager(QObject):
    """
    Централизованный менеджер данных для работы с камерами, регионами и цепочками обработки.
    Интегрирован с системой рецептов SortData.
    """
    
    # Сигналы для синхронизации между виджетами
    camera_changed = pyqtSignal(str)  # camera_id
    region_changed = pyqtSignal(str, str)  # camera_id, region_name
    chain_changed = pyqtSignal(str, str)  # camera_id, region_name
    data_changed = pyqtSignal()  # Общее изменение данных
    
    def __init__(self, sort_data=None):
        super().__init__()
        self.sort_data = sort_data if sort_data is not None else SortData()
        
        # Структура данных в памяти:
        # {
        #   "cameras": {
        #     "camera_0": {
        #       "name": "Camera 1",
        #       "hikvision_params": {"Frame Rate": 30.0, "Exposure": 10000, "Gain": 5.0},
        #       "regions": {
        #         "main_image": {
        #           "x1": 0, "y1": 0, "x2": 3840, "y2": 2160,
        #           "enabled": True,
        #           "is_main": True,
        #           "processing_enabled": True,
        #           "chains": [
        #             {"processor_id": "rgb", "enabled": True, "params": {}}
        #           ]
        #         },
        #         "region_1": {...}
        #       }
        #     }
        #   }
        # }
        self._data = {"cameras": {}}
        
        # Текущая выбранная камера
        self._current_camera_id = None
        
        # Загружаем данные из текущего рецепта
        self._load_from_recipe()
    
    def _load_from_recipe(self):
        """Загрузить данные из текущего рецепта"""
        try:
            current_recipe = self.sort_data.get_current_recipe_number()
            recipe_data = self.sort_data.get_recipe(current_recipe)
            
            # Проверяем есть ли структура cameras в рецепте
            if "cameras" in recipe_data:
                cameras_data = recipe_data["cameras"]
                if isinstance(cameras_data, str):
                    cameras_data = json.loads(cameras_data)
                self._data["cameras"] = cameras_data
            else:
                # Инициализируем пустую структуру
                self._data["cameras"] = {}
            
            # Если есть старая структура regions и region_chains, мигрируем
            if "regions" in recipe_data and "region_chains" in recipe_data:
                self._migrate_old_structure(recipe_data)
        except Exception as e:
            print(f"Ошибка загрузки данных из рецепта: {e}")
            import traceback
            traceback.print_exc()
    
    def _migrate_old_structure(self, recipe_data):
        """Миграция старой структуры данных (regions, region_chains) в новую (cameras)"""
        try:
            regions_str = recipe_data.get("regions", "[]")
            chains_str = recipe_data.get("region_chains", "{}")
            
            if isinstance(regions_str, str):
                regions = json.loads(regions_str)
            else:
                regions = regions_str
            
            if isinstance(chains_str, str):
                chains = json.loads(chains_str)
            else:
                chains = chains_str
            
            # Создаем камеру по умолчанию если её нет
            if not self._data["cameras"]:
                camera_id = "camera_0"
                self._data["cameras"][camera_id] = {
                    "name": "Camera 1",
                    "hikvision_params": {
                        "Frame Rate": recipe_data.get("Frame Rate", 0.0),
                        "Exposure": recipe_data.get("Exposure", 0),
                        "Gain": recipe_data.get("Gain", 0.0)
                    },
                    "regions": {}
                }
            
            # Используем первую камеру или создаем новую
            camera_id = list(self._data["cameras"].keys())[0] if self._data["cameras"] else "camera_0"
            camera = self._data["cameras"][camera_id]
            
            # Добавляем основное изображение как регион
            if "main_image" not in camera["regions"]:
                camera["regions"]["main_image"] = {
                    "x1": 0, "y1": 0, "x2": 3840, "y2": 2160,
                    "enabled": True,
                    "is_main": True,
                    "processing_enabled": True,
                    "chains": []
                }
            
            # Мигрируем регионы
            for region in regions:
                if isinstance(region, dict):
                    region_name = region.get("name", "region_1")
                    if region_name not in camera["regions"]:
                        camera["regions"][region_name] = {
                            "x1": region.get("x1", 0),
                            "y1": region.get("y1", 0),
                            "x2": region.get("x2", 0),
                            "y2": region.get("y2", 0),
                            "enabled": region.get("enabled", True),
                            "is_main": False,
                            "processing_enabled": region.get("processing_enabled", True),
                            "chains": chains.get(region_name, [])
                        }
            camera["region_order"] = list(camera["regions"].keys())
        except Exception as e:
            print(f"Ошибка миграции старой структуры: {e}")
            import traceback
            traceback.print_exc()
    
    def save_to_recipe(self, recipe_id="backup"):
        """Сохранить текущие данные в рецепт"""
        try:
            # Получаем текущие данные рецепта
            recipe_data = self.sort_data.get_recipe(recipe_id)
            
            # Обновляем структуру cameras
            recipe_data["cameras"] = json.dumps(self._data["cameras"], ensure_ascii=False)
            
            # Сохраняем в рецепт
            self.sort_data.set_recipe(recipe_id, recipe_data)
            
            self.data_changed.emit()
        except Exception as e:
            print(f"Ошибка сохранения данных в рецепт {recipe_id}: {e}")
            import traceback
            traceback.print_exc()
    
    def get_cameras(self):
        """Получить список всех камер"""
        return list(self._data["cameras"].keys())
    
    def get_camera(self, camera_id):
        """Получить данные камеры"""
        return self._data["cameras"].get(camera_id, {})
    
    def add_camera(self, camera_id=None, name=None):
        """Добавить новую камеру"""
        if camera_id is None:
            camera_id = f"camera_{len(self._data['cameras'])}"
        
        if camera_id not in self._data["cameras"]:
            self._data["cameras"][camera_id] = {
                "name": name or f"Camera {len(self._data['cameras']) + 1}",
                "hikvision_params": {
                    "Frame Rate": 0.0,
                    "Exposure": 0,
                    "Gain": 0.0
                },
                "region_order": ["main_image"],
                "regions": {
                    "main_image": {
                        "x1": 0, "y1": 0, "x2": 3840, "y2": 2160,
                        "enabled": True,
                        "is_main": True,
                        "processing_enabled": True,
                        "chains": []
                    }
                }
            }
            self.camera_changed.emit(camera_id)
            self.data_changed.emit()
            return camera_id
        return None
    
    def set_current_camera(self, camera_id):
        """Установить текущую камеру"""
        if camera_id in self._data["cameras"]:
            self._current_camera_id = camera_id
            self.camera_changed.emit(camera_id)
    
    def get_current_camera_id(self):
        """Получить ID текущей камеры"""
        if self._current_camera_id and self._current_camera_id in self._data["cameras"]:
            return self._current_camera_id
        # Возвращаем первую камеру если текущая не установлена
        cameras = self.get_cameras()
        if cameras:
            return cameras[0]
        return None
    
    def get_regions(self, camera_id=None):
        """Получить список регионов для камеры (порядок: region_order или ключи dict)"""
        if camera_id is None:
            camera_id = self.get_current_camera_id()
        
        if camera_id and camera_id in self._data["cameras"]:
            cam = self._data["cameras"][camera_id]
            order = cam.get("region_order")
            if order:
                return [n for n in order if n in cam["regions"]]
            return list(cam["regions"].keys())
        return []
    
    def get_region(self, camera_id, region_name):
        """Получить данные региона"""
        if camera_id in self._data["cameras"]:
            return self._data["cameras"][camera_id]["regions"].get(region_name, {})
        return {}
    
    def add_region(self, camera_id, region_name, x1=0, y1=0, x2=100, y2=100, enabled=True, is_main=False, processing_enabled=True):
        """Добавить регион к камере"""
        if camera_id not in self._data["cameras"]:
            return False
        
        # Если это основной регион, снимаем флаг is_main с других регионов
        if is_main:
            for rname in self._data["cameras"][camera_id]["regions"]:
                self._data["cameras"][camera_id]["regions"][rname]["is_main"] = False
        
        self._data["cameras"][camera_id]["regions"][region_name] = {
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "enabled": enabled,
            "is_main": is_main,
            "processing_enabled": processing_enabled,
            "chains": []
        }
        order = self._data["cameras"][camera_id].setdefault("region_order", list(self._data["cameras"][camera_id]["regions"].keys()))
        if region_name not in order:
            order.append(region_name)
        
        self.region_changed.emit(camera_id, region_name)
        self.data_changed.emit()
        return True
    
    def update_region(self, camera_id, region_name, **kwargs):
        """Обновить параметры региона"""
        if camera_id not in self._data["cameras"]:
            return False
        
        if region_name not in self._data["cameras"][camera_id]["regions"]:
            return False
        
        region = self._data["cameras"][camera_id]["regions"][region_name]
        
        # Если устанавливаем is_main=True, снимаем флаг с других регионов
        if kwargs.get("is_main", False):
            for rname in self._data["cameras"][camera_id]["regions"]:
                if rname != region_name:
                    self._data["cameras"][camera_id]["regions"][rname]["is_main"] = False
        
        region.update(kwargs)
        
        self.region_changed.emit(camera_id, region_name)
        self.data_changed.emit()
        return True
    
    def delete_region(self, camera_id, region_name):
        """Удалить регион"""
        if camera_id in self._data["cameras"]:
            if region_name in self._data["cameras"][camera_id]["regions"]:
                # Нельзя удалить main_image
                if region_name == "main_image":
                    return False
                del self._data["cameras"][camera_id]["regions"][region_name]
                order = self._data["cameras"][camera_id].get("region_order")
                if order and region_name in order:
                    order.remove(region_name)
                self.region_changed.emit(camera_id, region_name)
                self.data_changed.emit()
                return True
        return False

    def move_region(self, camera_id, region_name, direction):
        """Переместить регион вверх (direction=-1) или вниз (direction=1)."""
        if camera_id not in self._data["cameras"]:
            return False
        order = self._data["cameras"][camera_id].get("region_order")
        if not order or region_name not in order:
            return False
        idx = order.index(region_name)
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(order):
            return False
        order[idx], order[new_idx] = order[new_idx], order[idx]
        self.region_changed.emit(camera_id, region_name)
        self.data_changed.emit()
        return True
    
    def copy_region(self, source_camera_id, source_region_name, target_camera_id, target_region_name=None):
        """Скопировать регион с одной камеры на другую"""
        source_region = self.get_region(source_camera_id, source_region_name)
        if not source_region:
            return False
        
        if target_region_name is None:
            target_region_name = source_region_name
        
        # Создаем копию региона
        new_region = source_region.copy()
        new_region["chains"] = [chain.copy() for chain in source_region.get("chains", [])]
        new_region["is_main"] = False  # Скопированный регион не может быть основным
        
        if target_camera_id not in self._data["cameras"]:
            self.add_camera(target_camera_id)
        
        self._data["cameras"][target_camera_id]["regions"][target_region_name] = new_region
        
        self.region_changed.emit(target_camera_id, target_region_name)
        self.data_changed.emit()
        return True
    
    def get_chains(self, camera_id, region_name):
        """Получить цепочки обработки для региона"""
        region = self.get_region(camera_id, region_name)
        return region.get("chains", [])
    
    def add_chain_step(self, camera_id, region_name, processor_id, params=None, enabled=True):
        """Добавить шаг в цепочку обработки региона"""
        if camera_id not in self._data["cameras"]:
            return False
        
        if region_name not in self._data["cameras"][camera_id]["regions"]:
            return False
        
        if "chains" not in self._data["cameras"][camera_id]["regions"][region_name]:
            self._data["cameras"][camera_id]["regions"][region_name]["chains"] = []
        
        step = {
            "processor_id": processor_id,
            "params": params or {},
            "enabled": enabled
        }
        
        self._data["cameras"][camera_id]["regions"][region_name]["chains"].append(step)
        
        self.chain_changed.emit(camera_id, region_name)
        self.data_changed.emit()
        return True
    
    def update_chain_step(self, camera_id, region_name, step_index, **kwargs):
        """Обновить шаг цепочки"""
        if camera_id not in self._data["cameras"]:
            return False
        
        if region_name not in self._data["cameras"][camera_id]["regions"]:
            return False
        
        chains = self._data["cameras"][camera_id]["regions"][region_name]["chains"]
        if 0 <= step_index < len(chains):
            chains[step_index].update(kwargs)
            self.chain_changed.emit(camera_id, region_name)
            self.data_changed.emit()
            return True
        return False
    
    def delete_chain_step(self, camera_id, region_name, step_index):
        """Удалить шаг из цепочки"""
        if camera_id not in self._data["cameras"]:
            return False
        
        if region_name not in self._data["cameras"][camera_id]["regions"]:
            return False
        
        chains = self._data["cameras"][camera_id]["regions"][region_name]["chains"]
        if 0 <= step_index < len(chains):
            chains.pop(step_index)
            self.chain_changed.emit(camera_id, region_name)
            self.data_changed.emit()
            return True
        return False

    def move_chain_step(self, camera_id, region_name, step_index, direction):
        """Переместить шаг цепочки вверх (direction=-1) или вниз (direction=1)."""
        if camera_id not in self._data["cameras"]:
            return False
        if region_name not in self._data["cameras"][camera_id]["regions"]:
            return False
        chains = self._data["cameras"][camera_id]["regions"][region_name]["chains"]
        if step_index < 0 or step_index >= len(chains):
            return False
        new_idx = step_index + direction
        if new_idx < 0 or new_idx >= len(chains):
            return False
        chains[step_index], chains[new_idx] = chains[new_idx], chains[step_index]
        self.chain_changed.emit(camera_id, region_name)
        self.data_changed.emit()
        return True
    
    def set_camera_hikvision_params(self, camera_id, params):
        """Установить параметры Hikvision для камеры"""
        if camera_id not in self._data["cameras"]:
            return False
        
        self._data["cameras"][camera_id]["hikvision_params"].update(params)
        self.camera_changed.emit(camera_id)
        self.data_changed.emit()
        return True
    
    def get_camera_hikvision_params(self, camera_id):
        """Получить параметры Hikvision для камеры"""
        camera = self.get_camera(camera_id)
        return camera.get("hikvision_params", {})

