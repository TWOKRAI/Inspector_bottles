# -*- coding: utf-8 -*-
"""
Инструменты конвертации регистров в различные форматы.
"""
import json
from typing import Dict, Any
from .manager import RegistersManager

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


class RegistersConverter:
    """
    Конвертация регистров в различные форматы.
    Поддерживает JSON, YAML, dict и другие форматы.
    """
    
    @staticmethod
    def to_dict(registers: RegistersManager) -> Dict[str, Any]:
        """
        Экспорт регистров в словарь Python.
        
        Args:
            registers: Экземпляр RegistersManager
            
        Returns:
            dict: Словарь со всеми регистрами
        """
        return registers.model_dump_all()
    
    @staticmethod
    def to_json(registers: RegistersManager, indent: int = 2, ensure_ascii: bool = False) -> str:
        """
        Экспорт регистров в JSON строку.
        
        Args:
            registers: Экземпляр RegistersManager
            indent: Отступ для форматирования JSON
            ensure_ascii: Если True, все не-ASCII символы экранируются
            
        Returns:
            str: JSON строка
        """
        data = registers.model_dump_all(mode='json')
        return json.dumps(data, indent=indent, ensure_ascii=ensure_ascii)
    
    @staticmethod
    def from_json(json_str: str) -> RegistersManager:
        """
        Импорт регистров из JSON строки.
        
        Args:
            json_str: JSON строка с данными регистров
            
        Returns:
            RegistersManager: Экземпляр менеджера с загруженными данными
        """
        data = json.loads(json_str)
        registers = RegistersManager()
        registers.model_validate_all(data)
        return registers
    
    @staticmethod
    def to_yaml(registers: RegistersManager, default_flow_style: bool = False) -> str:
        """
        Экспорт регистров в YAML строку.
        
        Args:
            registers: Экземпляр RegistersManager
            default_flow_style: Если True, использует flow style для YAML
            
        Returns:
            str: YAML строка
            
        Raises:
            ImportError: Если модуль yaml не установлен
        """
        if not YAML_AVAILABLE:
            raise ImportError("Модуль yaml не установлен. Установите: pip install pyyaml")
        
        data = registers.model_dump_all()
        return yaml.dump(data, allow_unicode=True, default_flow_style=default_flow_style, sort_keys=False)
    
    @staticmethod
    def from_yaml(yaml_str: str) -> RegistersManager:
        """
        Импорт регистров из YAML строки.
        
        Args:
            yaml_str: YAML строка с данными регистров
            
        Returns:
            RegistersManager: Экземпляр менеджера с загруженными данными
            
        Raises:
            ImportError: Если модуль yaml не установлен
        """
        if not YAML_AVAILABLE:
            raise ImportError("Модуль yaml не установлен. Установите: pip install pyyaml")
        
        data = yaml.safe_load(yaml_str)
        registers = RegistersManager()
        registers.model_validate_all(data)
        return registers
    
    @staticmethod
    def validate_contracts(registers: RegistersManager) -> bool:
        """
        Валидация контрактов для бекенда.
        Проверяет что все регистры соответствуют ожидаемым схемам.
        
        Args:
            registers: Экземпляр RegistersManager
            
        Returns:
            bool: True если все контракты валидны
        """
        return registers.validate_all()
    
    @staticmethod
    def to_flat_dict(registers: RegistersManager, prefix: str = '') -> Dict[str, Any]:
        """
        Экспорт регистров в плоский словарь (для совместимости с рецептами).
        Все ключи будут иметь префикс имени регистра.
        
        Args:
            registers: Экземпляр RegistersManager
            prefix: Префикс для ключей (по умолчанию пустой)
            
        Returns:
            dict: Плоский словарь вида {'camera.source': 'camera', 'processing.crop_top': 0, ...}
        """
        flat_dict = {}
        all_registers = registers.model_dump_all()
        
        for register_name, register_data in all_registers.items():
            if isinstance(register_data, dict):
                for key, value in register_data.items():
                    if prefix:
                        flat_key = f"{prefix}.{register_name}.{key}"
                    else:
                        flat_key = f"{register_name}.{key}"
                    flat_dict[flat_key] = value
        
        return flat_dict
    
    @staticmethod
    def from_flat_dict(flat_dict: Dict[str, Any], prefix: str = '') -> RegistersManager:
        """
        Импорт регистров из плоского словаря (для совместимости с рецептами).
        
        Args:
            flat_dict: Плоский словарь вида {'camera.source': 'camera', 'processing.crop_top': 0, ...}
            prefix: Префикс для ключей (если использовался при экспорте)
            
        Returns:
            RegistersManager: Экземпляр менеджера с загруженными данными
        """
        registers = RegistersManager()
        structured_data = {}
        
        for flat_key, value in flat_dict.items():
            # Убираем префикс если есть
            if prefix and flat_key.startswith(prefix + '.'):
                flat_key = flat_key[len(prefix) + 1:]
            
            # Разбираем ключ: register_name.field_name
            parts = flat_key.split('.', 1)
            if len(parts) == 2:
                register_name, field_name = parts
                if register_name not in structured_data:
                    structured_data[register_name] = {}
                structured_data[register_name][field_name] = value
        
        registers.model_validate_all(structured_data)
        return registers
