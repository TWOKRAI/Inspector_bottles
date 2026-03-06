"""
Обработчик конфигурации процесса (Refactored).

Использует ProcessConfiguration из ProcessData для структурированного доступа к конфигурации.
Интегрируется с ConfigManager для глобальной конфигурации через shared_resources.
"""

from typing import Dict, Any, Optional

# Импорт из refactored config_module
from ...config_module import Config


class _CustomProcessConfig:
    """Обёртка над custom dict для совместимости с ProcessConfiguration."""

    def __init__(self, custom: dict):
        self._custom = custom or {}
        self._process = self._custom.get('process_config', {})
        self.managers = self._custom.get('component_managers_config', self._process.get('managers', {}))

    def get_manager_config(self, manager_name: str) -> Optional[Dict[str, Any]]:
        cfg = self.managers.get(manager_name) if isinstance(self.managers, dict) else None
        return cfg if cfg else None

    def get_module_config(self, module_name: str) -> Dict[str, Any]:
        mods = self._custom.get('module_configs', {})
        return mods.get(module_name, {}) if isinstance(mods, dict) else {}

    def get_process_config(self, key: str, default: Any = None) -> Any:
        parts = key.split('.')
        v = self._process
        for p in parts:
            if isinstance(v, dict) and p in v:
                v = v[p]
            else:
                return default
        return v

    def update_process_config(self, **kwargs) -> None:
        self._process.update(kwargs)


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
        # Получаем конфигурацию из ProcessData (config или custom)
        if shared_resources:
            process_data = shared_resources.get_process_data(process_name)
            if process_data:
                # ProcessData.config (ProcessConfiguration) или custom dict
                if hasattr(process_data, 'config') and process_data.config:
                    process_config = process_data.config.process.copy()
                    if config:
                        process_config.update(config)
                    super().__init__(process_config)
                    self.process_config = process_data.config
                elif process_data.custom:
                    # Конфиг из custom: process_config, component_managers_config, etc.
                    process_config = process_data.custom.get('process_config', {}).copy()
                    if config:
                        process_config.update(config)
                    super().__init__(process_config)
                    self.process_config = _CustomProcessConfig(process_data.custom)
                else:
                    super().__init__(config or {})
                    self.process_config = None
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
        
        # Проверяем ConfigManager (refactored ConfigManager использует get_config(name))
        if self.config_manager and hasattr(self.config_manager, 'get_process_config'):
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
        
        # Проверяем ConfigManager (refactored может не иметь get_process_config)
        if self.config_manager and hasattr(self.config_manager, 'get_process_config'):
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
            
            # Обновляем ConfigManager (если поддерживает API)
            if (self.config_manager and hasattr(self.config_manager, 'get_process_config')
                    and hasattr(self.config_manager, 'update_process_config')):
                process_config = self.config_manager.get_process_config()
                if process_config and self.process_name in process_config:
                    updated_config = process_config[self.process_name].copy()
                    updated_config.update(new_config)
                    self.config_manager.update_process_config({self.process_name: updated_config})
                else:
                    self.config_manager.update_process_config({self.process_name: new_config})
            
            return True
        except Exception as e:
            print(f"ProcessConfigHandler: Failed to update config: {e}")
            return False

