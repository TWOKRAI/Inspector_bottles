"""
Базовые Pydantic модели для компонентов системы.

Использует Pydantic v2 для валидации и работы с данными.
"""

import time
from typing import Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field, computed_field, model_validator, ConfigDict

from .types import ComponentType

# Импорт для расширенной ДНК (опционально)
try:
    from .dna import ComponentDNA, ComponentLocation, ResourceReference, ResourceType
except ImportError:
    # Для обратной совместимости
    ComponentDNA = None
    ComponentLocation = None
    ResourceReference = None
    ResourceType = None


class BaseComponentModel(BaseModel):
    """
    Базовая модель компонента - ДНК компонента.
    
    Хранит всю информацию о компоненте:
    - Тип и класс компонента
    - Уникальное имя
    - Состояние и статус
    - Метаданные
    - Временные метки для версионности
    """
    
    component_type: ComponentType
    component_class: str
    name: str
    status: str = Field(default="initializing")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # Расширенная информация о расположении (опционально)
    class_path: Optional[str] = None  # Полный путь к классу (module.Class)
    module_path: Optional[str] = None  # Путь к модулю
    file_path: Optional[str] = None  # Путь к файлу с кодом
    config_path: Optional[str] = None  # Путь к файлу конфигурации
    
    # Временные метки
    version: float = Field(default_factory=lambda: time.time())
    created_at: float = Field(default_factory=lambda: time.time())
    updated_at: float = Field(default_factory=lambda: time.time())
    
    @computed_field
    @property
    def created_at_dt(self) -> datetime:
        """Дата создания как datetime."""
        return datetime.fromtimestamp(self.created_at)
    
    @computed_field
    @property
    def updated_at_dt(self) -> datetime:
        """Дата обновления как datetime."""
        return datetime.fromtimestamp(self.updated_at)
    
    def update_timestamp(self):
        """Обновить временные метки."""
        self.version = time.time()
        self.updated_at = time.time()
    
    def update_status(self, status: str):
        """Обновить статус компонента."""
        self.status = status
        self.update_timestamp()
    
    def update_metadata(self, **kwargs):
        """Обновить метаданные."""
        self.metadata.update(kwargs)
        self.update_timestamp()
    
    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Получить значение метаданных."""
        return self.metadata.get(key, default)
    
    model_config = ConfigDict(
        # Использовать enum значения вместо объектов
        use_enum_values=True,
        # Разрешить произвольные типы для metadata
        arbitrary_types_allowed=True
    )


class BaseManagerModel(BaseComponentModel):
    """
    Модель менеджера.
    
    Расширяет BaseComponentModel специфичными для менеджеров полями:
    - Информация об инициализации
    - Список подключенных адаптеров
    - Статистика работы
    - Конфигурация менеджера
    """
    
    is_initialized: bool = False
    adapters: Dict[str, str] = Field(default_factory=dict)  # {name: class_path}
    stats: Dict[str, Any] = Field(default_factory=dict)
    config: Dict[str, Any] = Field(default_factory=dict)
    
    @model_validator(mode='after')
    def set_manager_type(self):
        """Установить тип компонента как MANAGER."""
        if self.component_type != ComponentType.MANAGER:
            self.component_type = ComponentType.MANAGER
        return self
    
    def set_initialized(self, value: bool = True):
        """Установить флаг инициализации."""
        self.is_initialized = value
        self.update_timestamp()
    
    def add_adapter(self, adapter_name: str, adapter_class: str):
        """Добавить адаптер."""
        self.adapters[adapter_name] = adapter_class
        self.update_timestamp()
    
    def remove_adapter(self, adapter_name: str):
        """Удалить адаптер."""
        if adapter_name in self.adapters:
            del self.adapters[adapter_name]
            self.update_timestamp()
    
    def update_stats(self, **kwargs):
        """Обновить статистику."""
        self.stats.update(kwargs)
        self.update_timestamp()
    
    def update_config(self, config: Dict[str, Any]):
        """Обновить конфигурацию менеджера."""
        self.config.update(config)
        self.update_timestamp()

