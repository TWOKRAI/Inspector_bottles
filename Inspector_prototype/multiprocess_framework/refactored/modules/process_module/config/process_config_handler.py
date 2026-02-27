"""
Обработчик конфигурации процесса (Refactored).

Использует ProcessConfiguration из ProcessData для структурированного доступа к конфигурации.
Интегрируется с ConfigManager для глобальной конфигурации через shared_resources.
"""

from typing import Dict, Any, Optional

# Импорт из старого модуля (временно, пока ConfigModule не рефакторен)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent / "modules"))
from Config_module import Config


class ProcessConfigHandler(Config):
    """
    Обработчик конфигурации процесса (Refactored).
    
    Использует ProcessConfiguration из ProcessData для структурированного доступа.
    ConfigManager создается локально в ProcessModule и передается через process.config_manager.
    """
    
    def __init__(
        self, 
        process_name: str,
        shared_resources=None,
        config: dict = None
    ):
        """
        Инициализация обработчика конфигурации.
        
        Args:
            process_name: Имя процесса
            shared_resources: SharedResourcesManager (легковесный контейнер с ProcessStateRegistry)
            config: Локальная конфигурация (опционально, берется из process_data если не указана)
        """
        # Получаем конфигурацию из ProcessData
        if shared_resources:
            process_data = shared_resources.get_process_data(process_name)
            if process_data and process_data.config:
                # Используем конфигурацию из ProcessData
                process_config = process_data.config.process.copy()
                if config:
                    process_config.update(config)
                super().__init__(process_config)
                self.process_config = process_data.config
            else:
                super().__init__(config or {})
                self.process_config = None
        else:
            super().__init__(config or {})
            self.process_config = None
        
        self.process_name = process_name
        self.shared_resources = shared_resources
        # ConfigManager создается локально в ProcessModule
        # Будет установлен через process.config_manager после создания ProcessModule
        self.config_manager = None  # Будет установлен через process.config_manager
    
    def get_managers_config(self) -> Dict[str, Any]:
        """
        Получить конфигурацию менеджеров.
        
        Сначала проверяет ProcessConfiguration из process_data, затем ConfigManager, затем локальную конфигурацию.
        """
        # Проверяем ProcessConfiguration из process_data
        if self.process_config:
            managers_config = self.process_config.managers
            if managers_config:
                return managers_config
        
        # Проверяем ConfigManager
        if self.config_manager:
            # Используем get_process_config для получения конфигурации процесса
            process_config = self.config_manager.get_process_config()
            if process_config and self.process_name in process_config:
                managers_config = process_config[self.process_name].get('managers', {})
                if managers_config:
                    return managers_config
        
        # Проверяем локальную конфигурацию
        return self.get('managers', {})
    
    def get_manager_config(self, manager_name: str) -> Dict[str, Any]:
        """
        Получить конфигурацию конкретного менеджера.
        
        Args:
            manager_name: Имя менеджера
            
        Returns:
            Словарь конфигурации менеджера
        """
        # Проверяем ProcessConfiguration из process_data
        if self.process_config:
            manager_config = self.process_config.get_manager_config(manager_name)
            if manager_config:
                return manager_config
        
        # Проверяем локальную конфигурацию
        managers_config = self.get_managers_config()
        return managers_config.get(manager_name, {}) if isinstance(managers_config, dict) else {}
    
    def get_module_config(self, module_name: str) -> Dict[str, Any]:
        """
        Получить конфигурацию модуля.
        
        Args:
            module_name: Имя модуля
            
        Returns:
            Словарь конфигурации модуля
        """
        # Проверяем ProcessConfiguration из process_data
        if self.process_config:
            return self.process_config.get_module_config(module_name)
        
        # Проверяем локальную конфигурацию
        return self.get(f'modules.{module_name}', {})
    
    def get_config(self, key: str, default: Any = None) -> Any:
        """
        Получить значение конфигурации по ключу.
        
        Сначала проверяет ProcessConfiguration из process_data, затем ConfigManager, затем локальную конфигурацию.
        
        Args:
            key: Ключ конфигурации (поддерживает точечную нотацию)
            default: Значение по умолчанию
            
        Returns:
            Значение конфигурации или default
        """
        # Проверяем ProcessConfiguration из process_data
        if self.process_config:
            value = self.process_config.get_process_config(key, default)
            if value != default:
                return value
        
        # Проверяем ConfigManager
        if self.config_manager:
            # Используем get_process_config для получения конфигурации процесса
            process_config = self.config_manager.get_process_config()
            if process_config and self.process_name in process_config:
                # Используем точечную нотацию для получения значения
                parts = key.split('.')
                value = process_config[self.process_name]
                for part in parts:
                    if isinstance(value, dict) and part in value:
                        value = value[part]
                    else:
                        value = default
                        break
                if value != default:
                    return value
        
        # Проверяем локальную конфигурацию
        return super().get(key, default)
    
    def update_config(self, new_config: Dict[str, Any]) -> bool:
        """
        Обновить конфигурацию процесса.
        
        Обновляет ProcessConfiguration в process_data и ConfigManager.
        
        Args:
            new_config: Новая конфигурация
            
        Returns:
            bool: True если обновление успешно
        """
        try:
            # Обновляем локальную конфигурацию
            self.update(new_config)
            
            # Обновляем ProcessConfiguration в process_data
            if self.process_config:
                self.process_config.update_process_config(**new_config)
            
            # Обновляем ConfigManager
            if self.config_manager:
                # Получаем текущую конфигурацию процесса
                process_config = self.config_manager.get_process_config()
                if process_config and self.process_name in process_config:
                    # Обновляем конфигурацию процесса
                    updated_config = process_config[self.process_name].copy()
                    updated_config.update(new_config)
                    self.config_manager.update_process_config({self.process_name: updated_config})
                else:
                    # Создаем новую конфигурацию процесса
                    self.config_manager.update_process_config({self.process_name: new_config})
            
            return True
        except Exception as e:
            print(f"ProcessConfigHandler: Failed to update config: {e}")
            return False

