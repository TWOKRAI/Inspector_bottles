# -*- coding: utf-8 -*-
"""
Менеджер всех регистров приложения.
Собирает все регистры в единую точку доступа для удобного управления.
"""
from typing import Dict, Any, Optional, Type
from pydantic import BaseModel
from .models import (
    CameraRegisters,
    ProcessingRegisters,
    PostProcessingRegisters,
    VisualRegisters,
    DrawRegisters,
    RobotRegisters,
    ConveyorRegisters,
    NeurounRegisters,
    HikvisionRegisters,
    FrameProcessRegisters,
)
from .models.data import CameraData, RegionData, ChainStepData


class RegistersManager:
    """
    Менеджер всех регистров приложения.
    Предоставляет единую точку доступа ко всем регистрам и методы для работы с ними.
    Поддерживает интернационализацию через TranslationManager.
    """
    """
    Менеджер всех регистров приложения.
    Предоставляет единую точку доступа ко всем регистрам и методы для работы с ними.
    """
    
    def __init__(self, translation_manager: Optional[Any] = None):
        """
        Инициализация всех регистров с значениями по умолчанию.
        
        Args:
            translation_manager: Опциональный TranslationManager для интернационализации
        """
        self.camera = CameraRegisters()
        self.processing = ProcessingRegisters()
        self.post_processing = PostProcessingRegisters()
        self.visual = VisualRegisters()
        self.draw = DrawRegisters()
        self.robot = RobotRegisters()
        self.conveyor = ConveyorRegisters()
        self.neuroun = NeurounRegisters()
        self.hikvision = HikvisionRegisters()
        self.frame_process = FrameProcessRegisters()
        
        # Схемы данных (для валидации структур данных)
        self.data_schemas: Dict[str, Type[BaseModel]] = {
            'camera': CameraData,
            'region': RegionData,
            'chain_step': ChainStepData,
        }
        
        # Менеджер переводов (опционально)
        self.translation_manager = translation_manager
    
    def model_dump_all(self) -> Dict[str, Any]:
        """
        Экспорт всех регистров в словарь.
        
        Returns:
            dict: Словарь со всеми регистрами, где ключ - имя регистра, значение - его данные
        """
        return {
            'camera': self.camera.model_dump(),
            'processing': self.processing.model_dump(),
            'post_processing': self.post_processing.model_dump(),
            'visual': self.visual.model_dump(),
            'draw': self.draw.model_dump(),
            'robot': self.robot.model_dump(),
            'conveyor': self.conveyor.model_dump(),
            'neuroun': self.neuroun.model_dump(),
            'hikvision': self.hikvision.model_dump(),
            'frame_process': self.frame_process.model_dump(),
        }
    
    def model_validate_all(self, data: Dict[str, Any], strict: bool = False):
        """
        Загрузка всех регистров из словаря.
        
        Args:
            data: Словарь с данными регистров (ключ - имя регистра, значение - данные)
            strict: Если True, строгая валидация (не допускает дополнительные поля)
        """
        if 'camera' in data:
            self.camera = CameraRegisters.model_validate(data['camera'], strict=strict)
        if 'processing' in data:
            self.processing = ProcessingRegisters.model_validate(data['processing'], strict=strict)
        if 'post_processing' in data:
            self.post_processing = PostProcessingRegisters.model_validate(data['post_processing'], strict=strict)
        if 'visual' in data:
            self.visual = VisualRegisters.model_validate(data['visual'], strict=strict)
        if 'draw' in data:
            self.draw = DrawRegisters.model_validate(data['draw'], strict=strict)
        if 'robot' in data:
            self.robot = RobotRegisters.model_validate(data['robot'], strict=strict)
        if 'conveyor' in data:
            self.conveyor = ConveyorRegisters.model_validate(data['conveyor'], strict=strict)
        if 'neuroun' in data:
            self.neuroun = NeurounRegisters.model_validate(data['neuroun'], strict=strict)
        if 'hikvision' in data:
            self.hikvision = HikvisionRegisters.model_validate(data['hikvision'], strict=strict)
        if 'frame_process' in data:
            self.frame_process = FrameProcessRegisters.model_validate(data['frame_process'], strict=strict)
    
    def get_register(self, name: str) -> Optional[Any]:
        """
        Получить регистр по имени.
        
        Args:
            name: Имя регистра (например, 'camera', 'processing')
            
        Returns:
            Экземпляр регистра или None если не найден
        """
        return getattr(self, name, None)
    
    def reset_all(self):
        """Сбросить все регистры к значениям по умолчанию"""
        self.__init__()
    
    def validate_all(self) -> bool:
        """
        Валидация всех регистров.
        
        Returns:
            bool: True если все регистры валидны
        """
        try:
            # Просто проверяем что все модели можно сериализовать
            self.model_dump_all()
            return True
        except Exception:
            return False
    
    def validate_data(self, data_type: str, data: Any) -> bool:
        """
        Валидация данных по схеме из регистров.
        
        Args:
            data_type: Тип данных ('camera', 'region', 'chain_step')
            data: Данные для валидации (dict или модель)
            
        Returns:
            bool: True если данные валидны
        """
        schema = self.data_schemas.get(data_type)
        if schema:
            try:
                if isinstance(data, schema):
                    return True
                schema.model_validate(data)
                return True
            except Exception:
                return False
        return False
    
    def get_data_schema(self, data_type: str) -> Optional[Type[BaseModel]]:
        """
        Получить схему данных по типу.
        
        Args:
            data_type: Тип данных ('camera', 'region', 'chain_step')
            
        Returns:
            Класс модели или None если не найден
        """
        return self.data_schemas.get(data_type)
    
    def get_field_description(self, register_name: str, field_name: str, 
                             language: Optional[str] = None) -> str:
        """
        Получить описание поля из модели (единый источник истины).
        Поддерживает интернационализацию через TranslationManager.
        
        Приоритет:
        1. Перевод из метаданных (info_i18n[language]) если указан язык
        2. json_schema_extra['info']
        3. description
        
        Args:
            register_name: Имя регистра (например, 'processing')
            field_name: Имя поля (например, 'crop_top')
            language: Код языка для перевода (например, 'en', 'ru'). Если None, используется текущий язык из TranslationManager
            
        Returns:
            str: Описание поля из модели (переведённое если доступно)
        """
        metadata = self.get_field_metadata(register_name, field_name, language=language)
        
        # Используем TranslationManager если доступен
        if self.translation_manager:
            return self.translation_manager.translate_metadata(metadata, field='info')
        
        # Fallback: проверяем i18n вручную
        if language:
            info_i18n = metadata.get('info_i18n', {})
            if isinstance(info_i18n, dict):
                translated = info_i18n.get(language)
                if translated:
                    return translated
        
        # Возвращаем обычное описание
        return metadata.get('info') or metadata.get('description', '')
    
    def get_field_descriptions(self, separator: str = '.') -> Dict[str, str]:
        """
        Получить описания всех полей из всех регистров.
        
        Args:
            separator: Разделитель для ключей (по умолчанию '.')
            
        Returns:
            dict: { 'register_name.field_name': 'описание' }
        """
        descriptions = {}
        
        register_names = [
            'camera', 'processing', 'post_processing', 'visual',
            'draw', 'robot', 'conveyor', 'neuroun', 'hikvision', 'frame_process'
        ]
        
        for register_name in register_names:
            register = getattr(self, register_name, None)
            if register:
                for field_name, field_info in register.model_fields.items():
                    field_key = f"{register_name}{separator}{field_name}"
                    
                    # Приоритет: json_schema_extra['info'] > description
                    json_schema_extra = field_info.json_schema_extra or {}
                    info = json_schema_extra.get('info', '')
                    
                    if not info:
                        info = field_info.description or ''
                    
                    descriptions[field_key] = info
        
        return descriptions
    
    def get_field_metadata(self, register_name: str, field_name: str,
                           language: Optional[str] = None) -> Dict[str, Any]:
        """
        Получить все метаданные поля (description, info, unit, range, и т.д.).
        Поддерживает интернационализацию через TranslationManager.
        
        Args:
            register_name: Имя регистра
            field_name: Имя поля
            language: Код языка для перевода (опционально)
            
        Returns:
            dict: Метаданные поля {
                'description': ..., 
                'info': ..., 
                'info_i18n': {...},  # Переводы описания
                'description_i18n': {...},  # Переводы краткого описания
                'unit': ..., 
                'range': ..., 
                'min': ..., 
                'max': ..., 
                'access_level': ..., 
                'examples': ..., 
                'default': ...
            }
        """
        register = getattr(self, register_name, None)
        if not register:
            return {}
        
        field_info = register.model_fields.get(field_name)
        if not field_info:
            return {}
        
        json_schema_extra = field_info.json_schema_extra or {}
        
        # Парсим диапазон из строки "min-max" или используем отдельные min/max
        range_str = json_schema_extra.get('range', '')
        min_val = json_schema_extra.get('min', None)
        max_val = json_schema_extra.get('max', None)
        
        # Если диапазон в строковом формате "0-100", парсим его
        if range_str and not min_val and not max_val:
            try:
                if '-' in range_str:
                    parts = range_str.split('-', 1)
                    if len(parts) == 2:
                        min_val = int(parts[0]) if parts[0].strip() else None
                        max_val = int(parts[1]) if parts[1].strip() else None
            except (ValueError, AttributeError):
                pass
        
        metadata = {
            'description': field_info.description or '',
            'info': json_schema_extra.get('info', ''),
            'unit': json_schema_extra.get('unit', ''),
            'range': range_str,
            'min': min_val,
            'max': max_val,
            'access_level': json_schema_extra.get('access_level', 0),
            'examples': json_schema_extra.get('examples', []),
            'default': field_info.default if hasattr(field_info, 'default') else None,
            'readonly': json_schema_extra.get('readonly', False),
            'hidden': json_schema_extra.get('hidden', False),
        }
        
        # Добавляем переводы если есть
        if 'info_i18n' in json_schema_extra:
            metadata['info_i18n'] = json_schema_extra['info_i18n']
        if 'description_i18n' in json_schema_extra:
            metadata['description_i18n'] = json_schema_extra['description_i18n']
        
        # Если указан язык и есть TranslationManager, применяем переводы
        if language and self.translation_manager:
            # Переводим info и description
            if 'info_i18n' in metadata:
                translated_info = metadata['info_i18n'].get(language)
                if translated_info:
                    metadata['info'] = translated_info
            if 'description_i18n' in metadata:
                translated_desc = metadata['description_i18n'].get(language)
                if translated_desc:
                    metadata['description'] = translated_desc
        
        return metadata
    
    def validate_field_value(self, register_name: str, field_name: str, value: Any, 
                            current_access_level: int = 0) -> tuple[bool, Optional[str]]:
        """
        Валидация значения поля с учётом диапазона и уровня доступа.
        
        Args:
            register_name: Имя регистра
            field_name: Имя поля
            value: Значение для валидации
            current_access_level: Текущий уровень доступа пользователя (0 = обычный, 1+ = администратор)
            
        Returns:
            tuple: (is_valid: bool, error_message: Optional[str])
        """
        metadata = self.get_field_metadata(register_name, field_name)
        
        if not metadata:
            return False, f"Поле {register_name}.{field_name} не найдено"
        
        # Проверка уровня доступа
        required_level = metadata.get('access_level', 0)
        if required_level > current_access_level:
            return False, f"Недостаточно прав доступа. Требуется уровень {required_level}"
        
        # Проверка диапазона для числовых значений
        if isinstance(value, (int, float)):
            min_val = metadata.get('min')
            max_val = metadata.get('max')
            
            if min_val is not None and value < min_val:
                return False, f"Значение {value} меньше минимального {min_val}"
            if max_val is not None and value > max_val:
                return False, f"Значение {value} больше максимального {max_val}"
        
        return True, None
    
    def get_fields_for_access_level(self, register_name: str, access_level: int = 0) -> Dict[str, Dict[str, Any]]:
        """
        Получить все поля регистра с метаданными, доступные для указанного уровня доступа.
        
        Args:
            register_name: Имя регистра
            access_level: Уровень доступа пользователя
            
        Returns:
            dict: {field_name: metadata_dict}
        """
        register = getattr(self, register_name, None)
        if not register:
            return {}
        
        fields = {}
        for field_name in register.model_fields.keys():
            metadata = self.get_field_metadata(register_name, field_name)
            required_level = metadata.get('access_level', 0)
            
            # Показываем только доступные поля
            if required_level <= access_level and not metadata.get('hidden', False):
                fields[field_name] = metadata
        
        return fields
    
    def can_modify_field(self, register_name: str, field_name: str, access_level: int = 0) -> bool:
        """
        Проверить, может ли пользователь с данным уровнем доступа изменять поле.
        
        Args:
            register_name: Имя регистра
            field_name: Имя поля
            access_level: Уровень доступа пользователя
            
        Returns:
            bool: True если поле можно изменять
        """
        metadata = self.get_field_metadata(register_name, field_name)
        if not metadata:
            return False
        
        # Проверка уровня доступа
        required_level = metadata.get('access_level', 0)
        if required_level > access_level:
            return False
        
        # Проверка readonly
        if metadata.get('readonly', False):
            return False
        
        return True
    
    def update_field_metadata(self, register_name: str, field_name: str, 
                             metadata_updates: Dict[str, Any], access_level: int = 0) -> tuple[bool, Optional[str]]:
        """
        Обновить метаданные поля (например, диапазон, уровень доступа).
        Требует администраторский уровень доступа.
        
        Args:
            register_name: Имя регистра
            field_name: Имя поля
            metadata_updates: Словарь с обновлениями метаданных {'min': 0, 'max': 100, 'access_level': 1, ...}
            access_level: Уровень доступа пользователя (должен быть >= 1 для изменения метаданных)
            
        Returns:
            tuple: (success: bool, error_message: Optional[str])
        """
        if access_level < 1:
            return False, "Требуется администраторский уровень доступа для изменения метаданных"
        
        register = getattr(self, register_name, None)
        if not register:
            return False, f"Регистр {register_name} не найден"
        
        field_info = register.model_fields.get(field_name)
        if not field_info:
            return False, f"Поле {field_name} не найдено в регистре {register_name}"
        
        # Внимание: Это изменение метаданных в runtime, но не в самой модели Pydantic
        # Для постоянного изменения нужно обновить файл модели
        # Здесь мы можем только логировать или сохранять в отдельный файл конфигурации
        
        # TODO: Реализовать сохранение динамических метаданных в отдельный файл
        # Например, App/Data/Registers/metadata_overrides.yaml
        
        return True, None
    
    def get_all_fields_metadata(self, access_level: int = 0, separator: str = '.') -> Dict[str, Dict[str, Any]]:
        """
        Получить метаданные всех полей всех регистров, доступных для указанного уровня доступа.
        
        Args:
            access_level: Уровень доступа пользователя
            separator: Разделитель для ключей (по умолчанию '.')
            
        Returns:
            dict: { 'register_name.field_name': metadata_dict }
        """
        all_metadata = {}
        
        register_names = [
            'camera', 'processing', 'post_processing', 'visual',
            'draw', 'robot', 'conveyor', 'neuroun', 'hikvision', 'frame_process'
        ]
        
        for register_name in register_names:
            fields = self.get_fields_for_access_level(register_name, access_level)
            for field_name, metadata in fields.items():
                field_key = f"{register_name}{separator}{field_name}"
                all_metadata[field_key] = metadata
        
        return all_metadata
