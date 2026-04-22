# -*- coding: utf-8 -*-
"""
Менеджер рецептов (сортов).
Отвечает за загрузку/сохранение рецептов из YAML.
Flow: save_recipe — model_dump_all → валидация (SchemaManager) → YAML → опционально VersionManager.
      load_recipe — YAML/get_document → валидация → model_validate_all.
"""
import os
import yaml
from typing import Dict, Any, Optional, Union
from .converter_manager import ConverterManager

# Типы ошибок для ErrorManager.report (контракт архитектуры)
VALIDATION_ERROR = "VALIDATION_ERROR"
RECIPE_LOAD_ERROR = "RECIPE_LOAD_ERROR"
RECIPE_SAVE_ERROR = "RECIPE_SAVE_ERROR"


class RecipeManager:
    """
    Менеджер рецептов (сортов).
    Работает с YAML файлом рецептов, использует ConverterManager для конвертации.
    Поддерживает валидацию через SchemaManager и версии через VersionManager.
    """
    
    def __init__(
        self,
        data_path: Optional[str] = None,
        converter: Optional[ConverterManager] = None,
        registers_manager: Optional[Any] = None,
        error_manager: Optional[Any] = None,
        schema_registry: Optional[Any] = None,
        version_manager: Optional[Any] = None,
    ):
        """
        Args:
            data_path: Путь к файлу рецептов (по умолчанию App/Data/Recipes/value_settings.yaml)
            converter: Экземпляр ConverterManager (создаётся автоматически если не передан)
            registers_manager: RegistersManager для описаний и model_dump_all/model_validate_all
            error_manager: Для report(type, context) при ошибках валидации/записи
            schema_registry: SchemaManager для валидации снимка рецепта (регистр = схема)
            version_manager: Опционально save_document/get_document для истории рецептов
        """
        if data_path is None:
            # base_dir = корень пакета App (recipe_manager в App/Core/Managers/)
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            data_path = os.path.join(base_dir, 'Data', 'Recipes', 'value_settings.yaml')
        
        self.data_path = os.path.abspath(data_path)
        self.converter = converter if converter is not None else ConverterManager()
        self.registers_manager = registers_manager
        self.error_manager = error_manager
        self.schema_registry = schema_registry
        self.version_manager = version_manager
        
        # Структура данных рецептов
        self._data = {
            "current_recipe": 0,
            "parameter_info": {},
            "recipes": {}
        }
        
        self.load()
    
    def load(self):
        """Загрузить данные из YAML. Если файла нет — оставить пустые рецепты."""
        if not os.path.isfile(self.data_path):
            # Создаём директорию если её нет
            os.makedirs(os.path.dirname(self.data_path), exist_ok=True)
            return
        
        try:
            with open(self.data_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
            if loaded:
                self._data["current_recipe"] = loaded.get("current_recipe", 0)
                self._data["parameter_info"] = loaded.get("parameter_info", {}) or {}
                self._data["recipes"] = loaded.get("recipes", {})
                if self._data["recipes"] is None:
                    self._data["recipes"] = {}
        except Exception as e:
            print(f"Ошибка загрузки YAML рецептов: {e}")
            import traceback
            traceback.print_exc()
    
    def save(self):
        """Сохранить данные в YAML."""
        try:
            os.makedirs(os.path.dirname(self.data_path) or ".", exist_ok=True)
            with open(self.data_path, "w", encoding="utf-8") as f:
                yaml.dump(self._data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        except Exception as e:
            print(f"Ошибка сохранения YAML рецептов: {e}")
            import traceback
            traceback.print_exc()
    
    def has_data(self) -> bool:
        """Есть ли хотя бы один рецепт."""
        return bool(self._data.get("recipes"))
    
    def get_recipe(self, recipe_id: Union[int, str]) -> Dict[str, Any]:
        """
        Получить рецепт по ID.
        
        Args:
            recipe_id: ID рецепта (int 0..21 или str 'default_value', 'real_value')
            
        Returns:
            dict: Словарь параметров рецепта
        """
        key = recipe_id if isinstance(recipe_id, str) else str(recipe_id)
        raw = self._data["recipes"].get(key, {}) or {}
        return dict(raw)
    
    def set_recipe(self, recipe_id: Union[int, str], params_dict: Dict[str, Any]):
        """
        Записать рецепт.
        
        Args:
            recipe_id: ID рецепта
            params_dict: Словарь параметров
        """
        key = recipe_id if isinstance(recipe_id, str) else str(recipe_id)
        if key not in self._data["recipes"]:
            self._data["recipes"][key] = {}
        self._data["recipes"][key] = {k: v for k, v in params_dict.items()}
        self.save()
    
    def get_current_recipe_number(self) -> int:
        """Получить номер текущего рецепта."""
        return self._data.get("current_recipe", 0)
    
    def set_current_recipe_number(self, number: int):
        """Установить номер текущего рецепта."""
        self._data["current_recipe"] = number
        self.save()
    
    def get_parameter_names(self) -> list:
        """Список имён параметров (из первого доступного рецепта)."""
        for key in ("default_value", "real_value") + tuple(str(i) for i in range(22)):
            r = self._data["recipes"].get(key, {})
            if r:
                return sorted(r.keys())
        return []
    
    def get_parameter_info(self, param_name: str, registers_manager: Optional[Any] = None) -> str:
        """
        Получить описание параметра.
        Приоритет: модель регистров (единый источник истины) > сохранённое в YAML
        
        Args:
            param_name: Имя параметра (может быть 'crop_top' или 'processing.crop_top')
            registers_manager: Опциональный RegistersManager для получения описаний из моделей
                               (если не передан, используется self.registers_manager)
            
        Returns:
            str: Описание параметра
        """
        # Используем переданный или сохранённый RegistersManager
        rm = registers_manager or self.registers_manager
        
        # Если есть RegistersManager, пытаемся получить описание из модели (единый источник истины)
        if rm:
            # Парсим имя параметра (может быть с префиксом регистра или без)
            if '.' in param_name:
                register_name, field_name = param_name.split('.', 1)
                description = rm.get_field_description(register_name, field_name)
                if description:
                    return description
            else:
                # Ищем поле во всех регистрах
                register_names = [
                    'camera', 'processing', 'post_processing', 'visual',
                    'draw', 'robot', 'conveyor', 'neuroun', 'hikvision', 'frame_process'
                ]
                for register_name in register_names:
                    description = rm.get_field_description(register_name, param_name)
                    if description:
                        return description
        
        # Fallback: используем сохранённое описание из YAML (может быть переопределено пользователем)
        return self._data.get("parameter_info", {}).get(param_name, "")
    
    def set_parameter_info(self, param_name: str, info_text: str):
        """Сохранить описание параметра."""
        if "parameter_info" not in self._data:
            self._data["parameter_info"] = {}
        self._data["parameter_info"][str(param_name)] = str(info_text)
        self.save()
    
    def set_recipe_param(self, recipe_id: Union[int, str], param_name: str, value: Any):
        """
        Обновить один параметр в рецепте.
        
        Args:
            recipe_id: ID рецепта
            param_name: Имя параметра
            value: Значение параметра
        """
        key = recipe_id if isinstance(recipe_id, str) else str(recipe_id)
        if key not in self._data["recipes"]:
            self._data["recipes"][key] = {}
        self._data["recipes"][key][str(param_name)] = value
        self.save()
    
    def init_from_params(self, params_dict: Dict[str, Any]):
        """
        Инициализировать хранилище из одного словаря параметров:
        создать default_value, real_value и рецепты 0..21.
        
        Args:
            params_dict: Словарь параметров
        """
        if not params_dict:
            return
        self._data["recipes"]["default_value"] = dict(params_dict)
        self._data["recipes"]["real_value"] = dict(params_dict)
        for i in range(22):
            self._data["recipes"][str(i)] = dict(params_dict)
        self.save()
    
    def save_structured_recipe(self, recipe_id: Union[int, str], registers_data: Dict[str, Any], 
                               cameras_data: Optional[Dict[str, Any]] = None):
        """
        Сохранить структурированный рецепт из регистров и данных камер.
        Использует ConverterManager для конвертации в плоский формат.
        
        Args:
            recipe_id: ID рецепта
            registers_data: Данные регистров (из RegistersManager.model_dump_all())
            cameras_data: Опциональные данные камер (из CameraManager)
        """
        # Конвертируем структурированные данные в плоский формат для совместимости
        flat_dict = {}
        
        # Конвертируем регистры в плоский формат
        for register_name, register_data in registers_data.items():
            register_flat = self.converter.to_flat_dict(register_data, prefix=register_name)
            flat_dict.update(register_flat)
        
        # Добавляем данные камер как JSON строку (для совместимости со старой структурой)
        if cameras_data:
            flat_dict["cameras"] = self.converter.to_json(cameras_data)
        
        self.set_recipe(recipe_id, flat_dict)
    
    def load_structured_recipe(self, recipe_id: Union[int, str]) -> Dict[str, Any]:
        """
        Загрузить структурированный рецепт.
        Возвращает данные в структурированном виде.
        
        Args:
            recipe_id: ID рецепта
            
        Returns:
            dict: Структурированные данные рецепта
        """
        flat_dict = self.get_recipe(recipe_id)
        
        # Конвертируем плоский формат обратно в структурированный
        structured = {}
        
        # Группируем по префиксам (register_name)
        register_groups = {}
        cameras_data = None
        
        for key, value in flat_dict.items():
            if key == "cameras":
                # Данные камер как JSON строка
                try:
                    cameras_data = self.converter.from_json(value)
                except Exception:
                    cameras_data = value
                continue
            
            # Разбираем ключ: register_name.field_name
            parts = key.split('.', 1)
            if len(parts) == 2:
                register_name, field_name = parts
                if register_name not in register_groups:
                    register_groups[register_name] = {}
                register_groups[register_name][field_name] = value
            else:
                # Старый формат без префикса
                structured[key] = value
        
        # Конвертируем группы обратно в структурированный формат
        for register_name, fields in register_groups.items():
            structured[register_name] = self.converter.from_flat_dict(fields, prefix='', separator='.')
        
        if cameras_data:
            structured["cameras"] = cameras_data
        
        return structured

    def save_recipe(
        self,
        recipe_id: Union[int, str],
        registers_manager: Optional[Any] = None,
        cameras_data: Optional[Dict[str, Any]] = None,
        save_version: bool = False,
    ) -> bool:
        """
        Полный flow сохранения рецепта (архитектура):
        RegistersManager.model_dump_all() → валидация (SchemaManager) → YAML → опционально VersionManager.
        При ошибках — ErrorManager.report(...).
        """
        rm = registers_manager or self.registers_manager
        if not rm or not hasattr(rm, "model_dump_all"):
            if self.error_manager and hasattr(self.error_manager, "report"):
                self.error_manager.report(RECIPE_SAVE_ERROR, {"reason": "no registers_manager"})
            return False
        snapshot = rm.model_dump_all()
        if self.schema_registry and hasattr(self.schema_registry, "validate_recipe"):
            ok, err = self.schema_registry.validate_recipe(
                snapshot,
                getattr(rm, "register_names", lambda: list(snapshot.keys()))(),
            )
            if not ok:
                if self.error_manager and hasattr(self.error_manager, "report"):
                    self.error_manager.report(VALIDATION_ERROR, {"message": err or "validate_recipe failed"})
                return False
        try:
            self.save_structured_recipe(recipe_id, snapshot, cameras_data)
        except Exception as e:
            if self.error_manager and hasattr(self.error_manager, "report"):
                self.error_manager.report(RECIPE_SAVE_ERROR, {"recipe_id": recipe_id, "exception": str(e)})
            return False
        if save_version and self.version_manager and hasattr(self.version_manager, "save_document"):
            try:
                self.version_manager.save_document("recipe", str(recipe_id), snapshot)
            except Exception as e:
                if self.error_manager and hasattr(self.error_manager, "report"):
                    self.error_manager.report(RECIPE_SAVE_ERROR, {
                        "recipe_id": recipe_id,
                        "stage": "version",
                        "exception": str(e),
                    })
        return True

    def load_recipe(
        self,
        recipe_id: Union[int, str],
        registers_manager: Optional[Any] = None,
        use_version: Optional[int] = None,
    ) -> bool:
        """
        Полный flow загрузки рецепта: YAML или get_document → валидация → model_validate_all.
        """
        rm = registers_manager or self.registers_manager
        if not rm or not hasattr(rm, "model_validate_all"):
            if self.error_manager and hasattr(self.error_manager, "report"):
                self.error_manager.report(RECIPE_LOAD_ERROR, {"reason": "no registers_manager"})
            return False
        snapshot = None
        if use_version is not None and self.version_manager and hasattr(self.version_manager, "get_document"):
            snapshot = self.version_manager.get_document("recipe", str(recipe_id), version=use_version)
        if snapshot is None:
            try:
                structured = self.load_structured_recipe(recipe_id)
                snapshot = {k: v for k, v in structured.items() if k != "cameras"}
            except Exception as e:
                if self.error_manager and hasattr(self.error_manager, "report"):
                    self.error_manager.report(RECIPE_LOAD_ERROR, {"recipe_id": recipe_id, "exception": str(e)})
                return False
        if self.schema_registry and hasattr(self.schema_registry, "validate_recipe"):
            ok, err = self.schema_registry.validate_recipe(
                snapshot,
                getattr(rm, "register_names", lambda: list(snapshot.keys()))(),
            )
            if not ok:
                if self.error_manager and hasattr(self.error_manager, "report"):
                    self.error_manager.report(VALIDATION_ERROR, {"message": err or "validate_recipe failed"})
                return False
        try:
            rm.model_validate_all(snapshot, strict=False)
        except Exception as e:
            if self.error_manager and hasattr(self.error_manager, "report"):
                self.error_manager.report(RECIPE_LOAD_ERROR, {"recipe_id": recipe_id, "exception": str(e)})
            return False
        return True
