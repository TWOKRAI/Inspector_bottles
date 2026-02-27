# -*- coding: utf-8 -*-
"""
Универсальный менеджер конвертации для всех компонентов системы.
Поддерживает конвертацию Pydantic моделей и структур данных в различные форматы.
"""
import json
from typing import Dict, Any, Type, Optional, Union, List
from pydantic import BaseModel

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


class ConverterManager:
    """
    Универсальный менеджер конвертации.
    Работает с любыми Pydantic моделями, словарями, списками.
    Используется в RegistersManager, RecipeManager, DataManager.
    """
    
    @staticmethod
    def to_dict(data: Any) -> Dict[str, Any]:
        """
        Конвертация в словарь Python.
        
        Args:
            data: Pydantic модель, словарь, список или другой объект
            
        Returns:
            dict: Словарь с данными
        """
        if isinstance(data, BaseModel):
            return data.model_dump()
        elif isinstance(data, dict):
            return {k: ConverterManager.to_dict(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [ConverterManager.to_dict(item) for item in data]
        else:
            return data
    
    @staticmethod
    def to_json(data: Any, indent: int = 2, ensure_ascii: bool = False) -> str:
        """
        Конвертация в JSON строку.
        
        Args:
            data: Pydantic модель, словарь, список
            indent: Отступ для форматирования JSON
            ensure_ascii: Если True, все не-ASCII символы экранируются
            
        Returns:
            str: JSON строка
        """
        if isinstance(data, BaseModel):
            data = data.model_dump(mode='json')
        elif isinstance(data, dict):
            data = ConverterManager.to_dict(data)
        return json.dumps(data, indent=indent, ensure_ascii=ensure_ascii)
    
    @staticmethod
    def from_json(json_str: str, model_class: Optional[Type[BaseModel]] = None) -> Any:
        """
        Конвертация из JSON строки с опциональной валидацией через модель.
        
        Args:
            json_str: JSON строка с данными
            model_class: Опциональный класс Pydantic модели для валидации
            
        Returns:
            Валидированная модель или словарь
        """
        data = json.loads(json_str)
        if model_class:
            return model_class.model_validate(data)
        return data
    
    @staticmethod
    def to_yaml(data: Any, default_flow_style: bool = False, sort_keys: bool = False) -> str:
        """
        Конвертация в YAML строку.
        
        Args:
            data: Pydantic модель, словарь, список
            default_flow_style: Если True, использует flow style для YAML
            sort_keys: Если True, сортирует ключи
            
        Returns:
            str: YAML строка
            
        Raises:
            ImportError: Если модуль yaml не установлен
        """
        if not YAML_AVAILABLE:
            raise ImportError("Модуль yaml не установлен. Установите: pip install pyyaml")
        
        if isinstance(data, BaseModel):
            data = data.model_dump()
        elif isinstance(data, dict):
            data = ConverterManager.to_dict(data)
        
        return yaml.dump(data, allow_unicode=True, default_flow_style=default_flow_style, sort_keys=sort_keys)
    
    @staticmethod
    def from_yaml(yaml_str: str, model_class: Optional[Type[BaseModel]] = None) -> Any:
        """
        Конвертация из YAML строки с опциональной валидацией.
        
        Args:
            yaml_str: YAML строка с данными
            model_class: Опциональный класс Pydantic модели для валидации
            
        Returns:
            Валидированная модель или словарь
            
        Raises:
            ImportError: Если модуль yaml не установлен
        """
        if not YAML_AVAILABLE:
            raise ImportError("Модуль yaml не установлен. Установите: pip install pyyaml")
        
        data = yaml.safe_load(yaml_str)
        if model_class:
            return model_class.model_validate(data)
        return data
    
    @staticmethod
    def to_flat_dict(data: Any, prefix: str = '', separator: str = '.') -> Dict[str, Any]:
        """
        Конвертация в плоский словарь (для совместимости с рецептами).
        Все ключи будут иметь префикс имени регистра.
        
        Args:
            data: Pydantic модель или словарь
            prefix: Префикс для ключей (по умолчанию пустой)
            separator: Разделитель для ключей (по умолчанию '.')
            
        Returns:
            dict: Плоский словарь вида {'camera.source': 'camera', 'processing.crop_top': 0, ...}
        """
        flat_dict = {}
        
        if isinstance(data, BaseModel):
            data = data.model_dump()
        
        if isinstance(data, dict):
            for key, value in data.items():
                if prefix:
                    flat_key = f"{prefix}{separator}{key}"
                else:
                    flat_key = str(key)
                
                if isinstance(value, (dict, BaseModel)):
                    # Рекурсивно обрабатываем вложенные структуры
                    nested = ConverterManager.to_flat_dict(value, flat_key, separator)
                    flat_dict.update(nested)
                elif isinstance(value, list):
                    # Для списков сохраняем как JSON строку или индексируем
                    flat_dict[flat_key] = json.dumps(value, ensure_ascii=False) if value else []
                else:
                    flat_dict[flat_key] = value
        
        return flat_dict
    
    @staticmethod
    def from_flat_dict(flat_dict: Dict[str, Any], model_class: Optional[Type[BaseModel]] = None, 
                       prefix: str = '', separator: str = '.') -> Any:
        """
        Конвертация из плоского словаря в структурированный формат.
        
        Args:
            flat_dict: Плоский словарь вида {'camera.source': 'camera', 'processing.crop_top': 0, ...}
            model_class: Опциональный класс Pydantic модели для валидации
            prefix: Префикс для ключей (если использовался при экспорте)
            separator: Разделитель для ключей
            
        Returns:
            Структурированный словарь или валидированная модель
        """
        structured_data = {}
        
        for flat_key, value in flat_dict.items():
            # Убираем префикс если есть
            if prefix and flat_key.startswith(prefix + separator):
                flat_key = flat_key[len(prefix) + separator:]
            
            # Разбираем ключ: part1.part2.part3...
            parts = flat_key.split(separator)
            
            # Строим вложенную структуру
            current = structured_data
            for i, part in enumerate(parts[:-1]):
                if part not in current:
                    current[part] = {}
                current = current[part]
            
            # Устанавливаем значение
            last_part = parts[-1]
            
            # Пытаемся распарсить JSON если значение строка
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, (dict, list)):
                        value = parsed
                except (json.JSONDecodeError, ValueError):
                    pass
            
            current[last_part] = value
        
        if model_class:
            return model_class.model_validate(structured_data)
        return structured_data
    
    @staticmethod
    def validate(data: Any, model_class: Type[BaseModel]) -> bool:
        """
        Валидация данных через Pydantic модель.
        
        Args:
            data: Данные для валидации (dict или модель)
            model_class: Класс Pydantic модели
            
        Returns:
            bool: True если данные валидны
        """
        try:
            if isinstance(data, model_class):
                return True
            model_class.model_validate(data)
            return True
        except Exception:
            return False
    
    @staticmethod
    def validate_and_convert(data: Any, model_class: Type[BaseModel]) -> Optional[BaseModel]:
        """
        Валидация и конвертация данных в модель.
        
        Args:
            data: Данные для валидации
            model_class: Класс Pydantic модели
            
        Returns:
            Валидированная модель или None если валидация не прошла
        """
        try:
            if isinstance(data, model_class):
                return data
            return model_class.model_validate(data)
        except Exception:
            return None
