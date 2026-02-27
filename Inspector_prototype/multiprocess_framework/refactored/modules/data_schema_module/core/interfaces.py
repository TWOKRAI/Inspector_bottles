"""
Упрощенные интерфейсы для модуля data_schema.

Убраны дублирующиеся методы, оставлены только основные.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Type, List, Tuple
from pydantic import BaseModel

from ..models.base import BaseManagerModel


class ISchemaManager(ABC):
    """Интерфейс для менеджера схем (реестр Pydantic моделей)."""
    
    @abstractmethod
    def register(self, schema_name: str, schema_class: Type[BaseModel]) -> bool:
        """Зарегистрировать схему."""
        pass
    
    @abstractmethod
    def get_schema(self, schema_name: str) -> Optional[Type[BaseModel]]:
        """Получить зарегистрированную схему."""
        pass
    
    @abstractmethod
    def has_schema(self, schema_name: str) -> bool:
        """Проверить наличие схемы."""
        pass
    
    @abstractmethod
    def create_instance(
        self,
        schema_name: str,
        data: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> BaseModel:
        """Создать экземпляр модели с дефолтными значениями."""
        pass
    
    @abstractmethod
    def get_defaults(self, schema_name: str) -> Dict[str, Any]:
        """Получить дефолтные значения схемы."""
        pass
    
    @abstractmethod
    def validate(
        self,
        schema_name: str,
        data: Dict[str, Any]
    ) -> Tuple[bool, Optional[BaseModel], Optional[str]]:
        """Валидировать данные по схеме."""
        pass
    
    @abstractmethod
    def list_schemas(self) -> List[str]:
        """Получить список всех зарегистрированных схем."""
        pass
    
    @abstractmethod
    def unregister(self, schema_name: str) -> bool:
        """Удалить схему из реестра."""
        pass
    
    @abstractmethod
    def clear(self):
        """Очистить все зарегистрированные схемы."""
        pass


class IStorageManager(ABC):
    """Интерфейс для менеджера хранения данных компонентов."""
    
    @abstractmethod
    def register_manager(
        self,
        manager_model: BaseManagerModel,
        process_name: Optional[str] = None
    ) -> bool:
        """Зарегистрировать менеджер в ProcessData."""
        pass
    
    @abstractmethod
    def get_manager_model(
        self,
        manager_name: str,
        manager_type: str,
        process_name: Optional[str] = None
    ) -> Optional[BaseManagerModel]:
        """Получить модель менеджера из ProcessData."""
        pass
    
    @abstractmethod
    def update_manager_model(
        self,
        manager_model: BaseManagerModel,
        process_name: Optional[str] = None
    ) -> bool:
        """Обновить модель менеджера в ProcessData."""
        pass
    
    @abstractmethod
    def get_manager_config(
        self,
        manager_type: str,
        manager_name: str,
        key: str,
        default: Any = None,
        process_name: Optional[str] = None
    ) -> Any:
        """Получить конфигурацию менеджера."""
        pass
    
    @abstractmethod
    def update_manager_config(
        self,
        manager_type: str,
        manager_name: str,
        key: str,
        value: Any,
        process_name: Optional[str] = None
    ) -> bool:
        """Обновить конфигурацию менеджера."""
        pass
    
    @abstractmethod
    def remove_manager(
        self,
        manager_name: str,
        manager_type: Optional[str] = None,
        process_name: Optional[str] = None
    ) -> bool:
        """Удалить менеджера из ProcessData."""
        pass
    
    @abstractmethod
    def list_managers(
        self,
        process_name: Optional[str] = None,
        manager_type: Optional[str] = None
    ) -> List[str]:
        """Получить список имен менеджеров."""
        pass


class IVersionManager(ABC):
    """Интерфейс для менеджера версий (опциональный)."""
    
    @abstractmethod
    def create_version(
        self,
        manager_model: BaseManagerModel,
        comment: Optional[str] = None,
        author: Optional[str] = None,
        tags: Optional[List[str]] = None,
        process_name: Optional[str] = None
    ) -> int:
        """Создать новую версию модели."""
        pass
    
    @abstractmethod
    def get_current_version(
        self,
        manager_type: str,
        manager_name: str,
        process_name: Optional[str] = None
    ) -> int:
        """Получить текущую версию менеджера."""
        pass
    
    @abstractmethod
    def get_version(
        self,
        manager_type: str,
        manager_name: str,
        version: int,
        process_name: Optional[str] = None
    ) -> Optional[BaseManagerModel]:
        """Получить модель по версии."""
        pass
    
    @abstractmethod
    def rollback(
        self,
        manager_type: str,
        manager_name: str,
        target_version: int,
        process_name: Optional[str] = None,
        create_new_version: bool = True,
        comment: Optional[str] = None
    ) -> bool:
        """Откатиться к указанной версии."""
        pass
    
    @abstractmethod
    def get_version_history(
        self,
        manager_type: str,
        manager_name: str,
        process_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Получить историю версий."""
        pass
    
    @abstractmethod
    def compare_versions(
        self,
        manager_type: str,
        manager_name: str,
        version1: int,
        version2: int,
        process_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Сравнить две версии."""
        pass


class IDataConverter(ABC):
    """Интерфейс для конвертера данных."""
    
    @abstractmethod
    def model_to_dict(self, model: BaseModel, **kwargs) -> Dict[str, Any]:
        """Конвертировать Pydantic модель в словарь."""
        pass
    
    @abstractmethod
    def dict_to_model(self, data: Dict[str, Any], model_class: Type[BaseModel], **kwargs) -> BaseModel:
        """Конвертировать словарь в Pydantic модель."""
        pass
    
    @abstractmethod
    def model_to_json(self, model: BaseModel, **kwargs) -> str:
        """Конвертировать Pydantic модель в JSON строку."""
        pass
    
    @abstractmethod
    def json_to_model(self, json_str: str, model_class: Type[BaseModel], **kwargs) -> BaseModel:
        """Конвертировать JSON строку в Pydantic модель."""
        pass


class IDataValidator(ABC):
    """Интерфейс для валидатора данных."""
    
    @abstractmethod
    def validate(
        self,
        data: Dict[str, Any],
        model_class: Type[BaseModel],
        strict: bool = False
    ) -> Tuple[bool, Optional[BaseModel], Optional[str]]:
        """Валидировать данные по модели."""
        pass
    
    @abstractmethod
    def is_valid(
        self,
        data: Dict[str, Any],
        model_class: Type[BaseModel],
        strict: bool = False
    ) -> bool:
        """Проверить валидность данных без создания экземпляра."""
        pass
    
    @abstractmethod
    def get_validation_errors(
        self,
        data: Dict[str, Any],
        model_class: Type[BaseModel],
        strict: bool = False
    ) -> List[Dict[str, Any]]:
        """Получить список ошибок валидации."""
        pass


class IVisualizationFormatter(ABC):
    """Интерфейс для форматеров визуализации схем."""
    
    @abstractmethod
    def format(self, schema_name: str, schema_info: Dict[str, Any]) -> str:
        """
        Форматировать информацию о схеме.
        
        Args:
            schema_name: Имя схемы
            schema_info: Словарь с информацией о схеме (поля, типы, описания и т.д.)
            
        Returns:
            Отформатированная строка
        """
        pass
    
    @property
    @abstractmethod
    def format_name(self) -> str:
        """Имя формата (например, 'text', 'html', 'mermaid')."""
        pass


class IDocumentationFormatter(ABC):
    """Интерфейс для форматеров документации схем."""
    
    @abstractmethod
    def format_schema(
        self,
        schema_name: str,
        schema_info: Dict[str, Any],
        include_examples: bool = True
    ) -> str:
        """
        Форматировать документацию для одной схемы.
        
        Args:
            schema_name: Имя схемы
            schema_info: Словарь с информацией о схеме
            include_examples: Включить примеры использования
            
        Returns:
            Отформатированная документация
        """
        pass
    
    @abstractmethod
    def format_api_reference(
        self,
        schemas: List[str],
        schema_infos: Dict[str, Dict[str, Any]]
    ) -> str:
        """
        Форматировать API Reference для всех схем.
        
        Args:
            schemas: Список имен схем
            schema_infos: Словарь {schema_name: schema_info}
            
        Returns:
            Отформатированный API Reference
        """
        pass
    
    @property
    @abstractmethod
    def format_name(self) -> str:
        """Имя формата (например, 'markdown', 'rst', 'html')."""
        pass


class ISchemaVisualizer(ABC):
    """Интерфейс для визуализатора схем."""
    
    @abstractmethod
    def visualize_schema(
        self,
        schema_name: str,
        format: str = "text",
        include_defaults: bool = True,
        include_types: bool = True,
        include_descriptions: bool = True
    ) -> str:
        """Визуализировать схему в указанном формате."""
        pass
    
    @abstractmethod
    def register_formatter(self, formatter: IVisualizationFormatter):
        """Зарегистрировать новый форматер визуализации."""
        pass
    
    @abstractmethod
    def list_formats(self) -> List[str]:
        """Получить список доступных форматов."""
        pass


class ISchemaDocumentationGenerator(ABC):
    """Интерфейс для генератора документации."""
    
    @abstractmethod
    def generate_documentation(
        self,
        schema_name: Optional[str] = None,
        format: str = "markdown",
        include_examples: bool = True,
        include_defaults: bool = True
    ) -> str:
        """Сгенерировать документацию для схемы или всех схем."""
        pass
    
    @abstractmethod
    def register_formatter(self, formatter: IDocumentationFormatter):
        """Зарегистрировать новый форматер документации."""
        pass
    
    @abstractmethod
    def list_formats(self) -> List[str]:
        """Получить список доступных форматов."""
        pass


