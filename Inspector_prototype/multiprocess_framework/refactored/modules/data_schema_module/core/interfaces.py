# -*- coding: utf-8 -*-
"""
Интерфейсы (ABCs и Protocol) для модуля data_schema.

Ключевые интерфейсы:
    ISchemaManager       — реестр Pydantic-схем
    IStorageManager      — хранение компонентов в ProcessData
    IVersionManager      — версионирование конфигов
    IDataConverter       — конвертация одной модели
    IDataValidator       — валидация данных по модели
    IRegisterStorage     — протокол хранилища для RegistersContainer
                           (реализации: FileStorage, SQLiteStorage, RedisStorage ...)
    IVisualizationFormatter / IDocumentationFormatter — стратегии вывода схем
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, Type, runtime_checkable

from pydantic import BaseModel

try:
    from typing import Protocol
except ImportError:
    from typing_extensions import Protocol  # type: ignore[assignment]

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


# =============================================================================
# Протокол хранилища регистров (для подключения баз данных)
# =============================================================================

@runtime_checkable
class IRegisterStorage(Protocol):
    """
    Протокол хранилища для RegistersContainer.

    Позволяет менять бэкенд хранения без изменения бизнес-логики.

    Готовые реализации:
        FileStorage       — JSON-файлы (storage/file_storage.py)

    Будущие реализации (реализуйте этот же протокол):
        SQLiteStorage     — локальная БД (offline-first)
        PostgreSQLStorage — серверная СУБД
        RedisStorage      — in-memory с персистентностью
        S3Storage         — облачное хранилище

    Пример реализации:

        class SQLiteStorage:
            def load(self, container_name: str) -> dict: ...
            def save(self, container_name: str, data: dict) -> None: ...
            def exists(self, container_name: str) -> bool: ...
            def delete(self, container_name: str) -> bool: ...

        container.save(SQLiteStorage("app.db"), "main_process")
        container.load(SQLiteStorage("app.db"), "main_process")
    """

    def load(self, container_name: str) -> Dict[str, Any]:
        """Загрузить данные регистров по имени контейнера."""
        ...

    def save(self, container_name: str, data: Dict[str, Any]) -> None:
        """Сохранить данные регистров."""
        ...

    def exists(self, container_name: str) -> bool:
        """Проверить наличие сохранённых данных."""
        ...

    def delete(self, container_name: str) -> bool:
        """Удалить данные контейнера. Возвращает True если данные существовали."""
        ...


# TODO: RegistersContainer.async_save / async_load — реализовать когда
#       потребуется интеграция с Redis/PostgreSQL.
#       Пример реализации хранилища:
#
#       class RedisStorage:
#           async def load(self, name: str) -> dict: ...
#           async def save(self, name: str, data: dict) -> None: ...
#           async def exists(self, name: str) -> bool: ...
#           async def delete(self, name: str) -> bool: ...

@runtime_checkable
class IAsyncRegisterStorage(Protocol):
    """
    Async-версия IRegisterStorage для неблокирующих бэкендов.

    Для использования с Redis, PostgreSQL, S3 и другими async-хранилищами.

    TODO: Интегрировать в RegistersContainer через async_save / async_load:
        await container.async_save(storage, "main_process")
        await container.async_load(storage, "main_process")
    """

    async def load(self, container_name: str) -> Dict[str, Any]:
        """Асинхронно загрузить данные регистров."""
        ...

    async def save(self, container_name: str, data: Dict[str, Any]) -> None:
        """Асинхронно сохранить данные регистров."""
        ...

    async def exists(self, container_name: str) -> bool:
        """Асинхронно проверить наличие данных."""
        ...

    async def delete(self, container_name: str) -> bool:
        """Асинхронно удалить данные. Возвращает True если данные существовали."""
        ...
