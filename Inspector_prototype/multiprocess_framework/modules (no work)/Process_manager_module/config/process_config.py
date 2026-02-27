"""
Валидация конфигурации процессов.

ProcessConfig - класс для валидации конфигураций процессов в ConfigManager.
Наследуется от Config и используется для проверки корректности конфигураций.

ВАЖНО: Не путать с ProcessConfiguration в Shared_resources_module!
- ProcessConfig (здесь) - для валидации конфигураций в ConfigManager
- ProcessConfiguration (Shared_resources_module) - dataclass для хранения данных конфигурации в ProcessData

Может работать как напрямую, так и через ConfigManager.
"""

from typing import Dict, Any, Optional
from ...Config_module.base_config import Config


class ProcessConfig(Config):
    """
    Валидация конфигурации процессов.
    
    Используется для валидации конфигураций процессов в ConfigManager.
    Наследуется от Config для базовых операций (get, set, update и т.д.).
    Добавляет специфичные методы для валидации конфигураций процессов.
    
    ВАЖНО: Не путать с ProcessConfiguration в Shared_resources_module!
    - ProcessConfig (этот класс) - для валидации в ConfigManager
    - ProcessConfiguration - dataclass для хранения данных в ProcessData
    """
    
    def add_process_config(
        self, 
        name: str, 
        process_class, 
        priority: str = 'normal',
        config: dict = None,
        enabled: bool = True
    ) -> bool:
        """
        Добавить конфигурацию процесса с валидацией.
        
        Args:
            name: Имя процесса
            process_class: Класс процесса
            priority: Приоритет процесса
            config: Конфигурация процесса
            enabled: Включен ли процесс
            
        Returns:
            True если конфигурация добавлена, False если валидация не прошла
        """
        # Валидация
        is_valid, error = self.validate_config({
            'class': process_class,
            'priority': priority,
            'config': config,
            'enabled': enabled
        })
        if not is_valid:
            print(f"⚠️ Invalid config for {name}: {error}")
            return False
        
        self.set(name, {
            'class': process_class,
            'priority': priority,
            'config': config or {},
            'enabled': enabled
        })
        return True
    
    def get_process_config(self, name: str) -> Optional[Dict[str, Any]]:
        """Получить конфигурацию процесса."""
        return self.get(name)
    
    def get_enabled_configs(self) -> Dict[str, Dict[str, Any]]:
        """Получить только включенные конфигурации."""
        return {
            name: config 
            for name, config in self.data.items() 
            if isinstance(config, dict) and config.get('enabled', True)
        }
    
    def validate_config(self, config: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Валидация конфигурации процесса.
        
        Args:
            config: Словарь конфигурации для валидации
            
        Returns:
            (is_valid, error_message)
        """
        if not isinstance(config, dict):
            return False, "Config must be a dictionary"
        
        if 'class' not in config:
            return False, "Config must have 'class' field"
        
        process_class = config.get('class')
        # Проверяем что класс либо callable (объект класса), либо строка (путь к классу)
        if not (callable(process_class) or isinstance(process_class, str)):
            return False, "Process class must be callable or a string path to class"
        
        # Если это строка, пытаемся проверить что путь валидный
        if isinstance(process_class, str):
            if '.' not in process_class:
                return False, "Process class path must be in format 'module.path.ClassName'"
            # Проверяем что путь выглядит валидным (не пустой, не только точки)
            parts = process_class.split('.')
            if not all(part for part in parts):
                return False, "Process class path contains empty parts"
        
        priority = config.get('priority', 'normal')
        valid_priorities = ['high', 'normal', 'low', 'below_normal', 'above_normal']
        if priority not in valid_priorities:
            return False, f"Invalid priority: {priority}. Must be one of {valid_priorities}"
        
            # Валидация конфигурации консоли (опционально)
        console_config = config.get('console', {})
        if console_config:
            if not isinstance(console_config, dict):
                return False, "Console config must be a dictionary"
            # enabled - опциональное поле, должно быть bool (по умолчанию True)
            if 'enabled' in console_config and not isinstance(console_config['enabled'], bool):
                return False, "Console 'enabled' must be a boolean"
            # recipient - опциональное поле, должно быть строкой, списком строк или null
            if 'recipient' in console_config:
                recipient_val = console_config.get('recipient')
                if recipient_val is not None:
                    if isinstance(recipient_val, str):
                        pass  # Одна строка - ок
                    elif isinstance(recipient_val, list):
                        # Список должен содержать только строки
                        if not all(isinstance(item, str) for item in recipient_val):
                            return False, "Console 'recipient' list must contain only strings"
                    else:
                        return False, "Console 'recipient' must be a string, list of strings, or null"
            # title - опциональное поле, должно быть строкой или null
            if 'title' in console_config:
                title_val = console_config.get('title')
                if title_val is not None and not isinstance(title_val, str):
                    return False, "Console 'title' must be a string or null"
            # Обратная совместимость: group (deprecated, используйте recipient)
            if 'group' in console_config:
                group_val = console_config.get('group')
                if group_val is not None and not isinstance(group_val, str):
                    return False, "Console 'group' must be a string or null (deprecated, use 'recipient')"
        
        return True, None
    
    def load_from_dict(self, process_config: Dict[str, Dict[str, Any]]):
        """
        Загрузить конфигурации из словаря.
        
        Args:
            process_config: Словарь конфигураций процессов
        """
        for process_name, config in process_config.items():
            self.add_process_config(
                name=process_name,
                process_class=config['class'],
                priority=config.get('priority', 'normal'),
                config=config.get('config', {}),
                enabled=config.get('enabled', True)
            )
    
    @property
    def process_configs(self) -> Dict[str, Dict[str, Any]]:
        """
        Получить все конфигурации процессов (для обратной совместимости).
        
        Returns:
            Словарь всех конфигураций процессов
        """
        return self.data
