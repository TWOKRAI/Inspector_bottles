"""
ManagerData - данные менеджера.

Использует BaseManagerModel из data_schema (Pydantic v2) вместо BaseManagerData.
Использует утилиты из data_schema для работы с данными.
"""

from typing import Dict, Any, Optional, Callable

from ..Shared_resources_module.data_schema.models.base import BaseManagerModel
from ..Shared_resources_module.data_schema.utils import (
    get_nested_value,
    set_nested_value,
    convert_all_references,
)
from ..Shared_resources_module.data_schema.utils.reference import convert_reference_to_data


class ManagerData(BaseManagerModel):
    """
    Data класс для менеджеров (использует Pydantic v2).
    
    Наследуется от BaseManagerModel из data_schema модуля.
    Использует утилиты из data_schema для работы с данными.
    
    Наследует от BaseManagerModel:
    - Все поля из BaseComponentModel (component_type, component_class, name, status, metadata, version, etc.)
    - is_initialized, adapters, stats, config
    
    Пример использования:
        # Создание ManagerData
        manager_data = ManagerData(
            component_class="LoggerManager",
            name="logger_main",
            config={"log_level": "INFO"}
        )
        
        # Универсальные методы из data_schema.utils
        log_level = get_nested_value(manager_data.config, 'log_level')
        
        # Работа со ссылками
        from multiprocess_framework.modules.Shared_resources_module.data_schema import DataReference
        ref = DataReference("process:main_process", resolver=resolver_func)
        manager_data.config['process_ref'] = ref
    """
    
    def get_config_value(self, key: str, default: Any = None) -> Any:
        """Получить значение из config по точечной нотации."""
        return get_nested_value(self.config, key, default)
    
    def set_config_value(self, key: str, value: Any):
        """Установить значение в config по точечной нотации."""
        set_nested_value(self.config, key, value)
        self.update_timestamp()
    
    def convert_references_in_config(self, resolver: Optional[Callable] = None):
        """Конвертировать все ссылки в config в обычные данные."""
        self.config = convert_all_references(self.config, resolver)
        self.update_timestamp()
    
    def convert_reference_at_path(self, path: str, resolver: Optional[Callable] = None) -> bool:
        """Точечная конвертация ссылки по пути в config."""
        # Разбиваем путь на части
        keys = path.split('.')
        current = self.config
        
        # Находим объект по пути
        for key in keys[:-1]:
            if not isinstance(current, dict) or key not in current:
                return False
            current = current[key]
        
        # Конвертируем ссылку
        final_key = keys[-1]
        if isinstance(current, dict) and final_key in current:
            converted = convert_reference_to_data(current[final_key], resolver)
            if converted is not None:
                current[final_key] = converted
                self.update_timestamp()
                return True
        return False
