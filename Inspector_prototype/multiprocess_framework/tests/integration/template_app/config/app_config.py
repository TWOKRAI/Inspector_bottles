"""
Конфигурация шаблонного приложения.

Демонстрирует использование DataSchemaModule для работы с конфигурациями.
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from multiprocess_framework.modules.data_schema_module import SchemaRegistry


@dataclass
class AppConfig:
    """Конфигурация приложения."""
    
    # Настройки процессов
    vision_process_enabled: bool = True
    ai_process_enabled: bool = True
    db_process_enabled: bool = True
    ui_process_enabled: bool = False  # PyQt процесс (опционально)
    
    # Настройки воркеров
    vision_workers_count: int = 2
    ai_workers_count: int = 1
    db_workers_count: int = 1
    
    # Настройки очередей
    queue_maxsize: int = 100
    queue_timeout: float = 5.0
    
    # Настройки логирования
    log_level: str = "INFO"
    log_to_file: bool = True
    log_file_path: str = "logs/app.log"
    
    # Настройки роутера
    router_channels: Dict[str, Any] = field(default_factory=lambda: {
        'vision': {'type': 'queue', 'maxsize': 100},
        'ai': {'type': 'queue', 'maxsize': 100},
        'db': {'type': 'queue', 'maxsize': 100},
        'ui': {'type': 'queue', 'maxsize': 100},
    })
    
    # Метаданные
    metadata: Dict[str, Any] = field(default_factory=lambda: {
        'version': '1.0.0',
        'description': 'Template Application for Multiprocess Framework'
    })


class AppConfigManager:
    """Менеджер конфигурации приложения."""
    
    def __init__(self, config_manager: Optional[SchemaRegistry] = None):
        """
        Инициализация менеджера конфигурации.
        
        Args:
            config_manager: Реестр схем (опционально)
        """
        self.config_manager = config_manager
        self._config: Optional[AppConfig] = None
    
    def load_config(self, config_dict: Optional[Dict[str, Any]] = None) -> AppConfig:
        """
        Загрузка конфигурации.
        
        Args:
            config_dict: Словарь с конфигурацией (если None, используется дефолтная)
            
        Returns:
            AppConfig: Загруженная конфигурация
        """
        if config_dict is None:
            self._config = AppConfig()
        else:
            self._config = AppConfig(**config_dict)
        
        # Если есть config_manager, можно сохранить схему
        if self.config_manager:
            self._save_schema()
        
        return self._config
    
    def get_config(self) -> AppConfig:
        """Получить текущую конфигурацию."""
        if self._config is None:
            return self.load_config()
        return self._config
    
    def _save_schema(self):
        """Сохранить схему конфигурации в SchemaRegistry."""
        # SchemaRegistry работает с Pydantic моделями
        # Для простых случаев можно пропустить регистрацию схемы
        pass

