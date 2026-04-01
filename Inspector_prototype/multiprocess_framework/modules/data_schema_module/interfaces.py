# -*- coding: utf-8 -*-
"""
Публичный контракт data_schema_module.

Все протоколы и ABC определены здесь — без зависимости от внутренних
реализаций модуля. Другие модули фреймворка импортируют только отсюда.

Иерархия интерфейсов:
    Ядро схем:
        ISchema              — протокол любой схемы данных
        ISchemaRegistry      — реестр схем (без Singleton)
        ISchemaAdapter       — адаптер схемы для потребляющих модулей (НОВЫЙ)

    Хранилище:
        ISchemaStorage       — протокол хранилища (переименован из IRegisterStorage)
        IAsyncSchemaStorage  — async-версия (переименован из IAsyncRegisterStorage)

    Dict at Boundary:
        HasBuild             — конфиг с build() -> (name, dict)

    Сериализация:
        IDataConverter       — конвертация модели
        IDataValidator       — валидация данных

    Инструменты (для extensions/):
        IVisualizationFormatter
        IDocumentationFormatter
        ISchemaVisualizer
        ISchemaDocumentationGenerator

    Расширенные (для extensions/):
        IStorageManager      — хранение компонентов в ProcessData
        IVersionManager      — версионирование конфигов
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, Type, runtime_checkable

try:
    from typing import Protocol
except ImportError:
    from typing_extensions import Protocol  # type: ignore[assignment]


# =============================================================================
# Ядро: схемы
# =============================================================================

@runtime_checkable
class ISchema(Protocol):
    """
    Протокол для любой схемы данных (RegisterBase / SchemaBase).

    Реализуется через RegisterMixin + Pydantic BaseModel.
    Используется для type hints в адаптерах и реестре.
    """

    def model_dump(self) -> Dict[str, Any]: ...

    @classmethod
    def get_field_meta(cls, field_name: str) -> Any: ...

    @classmethod
    def get_all_fields_meta(cls) -> Dict[str, Any]: ...

    def update_field(
        self, field_name: str, value: Any, access_level: int = 0
    ) -> Tuple[bool, Optional[str]]: ...

    def validate_field(
        self, field_name: str, value: Any, access_level: int = 0
    ) -> Tuple[bool, Optional[str]]: ...


class ISchemaRegistry(ABC):
    """
    Интерфейс реестра схем.

    Реализация: SchemaRegistry (registry/schema_registry.py).
    Не Singleton — используйте get_default_registry() для глобального экземпляра
    или создайте SchemaRegistry() для изолированного (в тестах).
    """

    @abstractmethod
    def register(self, name: str, schema_class: Type) -> bool:
        """Зарегистрировать схему под именем."""
        ...

    @abstractmethod
    def get(self, name: str) -> Optional[Type]:
        """Получить класс схемы по имени."""
        ...

    @abstractmethod
    def has(self, name: str) -> bool:
        """Проверить наличие схемы."""
        ...

    @abstractmethod
    def list_schemas(self) -> List[str]:
        """Список всех зарегистрированных имён."""
        ...

    @abstractmethod
    def unregister(self, name: str) -> bool:
        """Удалить схему из реестра."""
        ...

    @abstractmethod
    def clear(self) -> None:
        """Очистить реестр."""
        ...


@runtime_checkable
class ISchemaAdapter(Protocol):
    """
    Протокол адаптера схемы для потребляющих модулей.

    Адаптеры живут в потребляющих модулях (Dependency Inversion):
        config_module/adapters/schema_adapter.py  — Schema -> дерево параметров
        router_module/adapters/schema_adapter.py  — Schema -> маршруты
        process_manager_module/adapters/...       — Schema -> process config dict

    Пример реализации:

        class ConfigSchemaAdapter:
            def adapt(self, schema_class: Type[SchemaBase], **options) -> Dict[str, Any]:
                return {
                    name: {"default": meta.default, "description": meta.description}
                    for name, meta in schema_class.get_all_fields_meta().items()
                }

            def adapt_instance(self, instance: SchemaBase, **options) -> Dict[str, Any]:
                return instance.model_dump()
    """

    def adapt(self, schema_class: Type, **options) -> Dict[str, Any]: ...

    def adapt_instance(self, schema_instance: Any, **options) -> Dict[str, Any]: ...


# =============================================================================
# Dict at Boundary
# =============================================================================

@runtime_checkable
class HasBuild(Protocol):
    """
    Протокол конфига с build() -> (name, dict).

    Реализуют Process1Config, Worker1Config, ErrorManagerConfig и др.
    Без зависимости от RegisterBase — любой объект с build() подходит.

    Пример:

        class MyConfig:
            def build(self) -> Tuple[str, Dict[str, Any]]:
                return "my_process", {"key": "value"}
    """

    def build(self) -> Tuple[str, Dict[str, Any]]: ...


# =============================================================================
# Хранилище регистров
# =============================================================================

@runtime_checkable
class ISchemaStorage(Protocol):
    """
    Протокол хранилища для RegistersContainer.

    Переименован из IRegisterStorage (алиас сохранён в _compat.py).
    Позволяет менять бэкенд хранения без изменения бизнес-логики.

    Готовые реализации:
        FileStorage       — JSON-файлы (serialization/file_storage.py)

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
    """

    def load(self, container_name: str) -> Dict[str, Any]: ...

    def save(self, container_name: str, data: Dict[str, Any]) -> None: ...

    def exists(self, container_name: str) -> bool: ...

    def delete(self, container_name: str) -> bool: ...


@runtime_checkable
class IAsyncSchemaStorage(Protocol):
    """
    Async-версия ISchemaStorage для неблокирующих бэкендов.

    Переименован из IAsyncRegisterStorage (алиас сохранён в _compat.py).
    Для использования с Redis, PostgreSQL, S3 и другими async-хранилищами.

    TODO: Интегрировать в RegistersContainer через async_save / async_load.
    """

    async def load(self, container_name: str) -> Dict[str, Any]: ...

    async def save(self, container_name: str, data: Dict[str, Any]) -> None: ...

    async def exists(self, container_name: str) -> bool: ...

    async def delete(self, container_name: str) -> bool: ...


# =============================================================================
# Сериализация
# =============================================================================

class IDataConverter(ABC):
    """Интерфейс для конвертера данных (реализация: serialization/converter.py)."""

    @abstractmethod
    def model_to_dict(self, model: Any, **kwargs) -> Dict[str, Any]:
        """Конвертировать Pydantic модель в словарь."""
        ...

    @abstractmethod
    def dict_to_model(self, data: Dict[str, Any], model_class: Type, **kwargs) -> Any:
        """Конвертировать словарь в Pydantic модель."""
        ...

    @abstractmethod
    def model_to_json(self, model: Any, **kwargs) -> str:
        """Конвертировать Pydantic модель в JSON строку."""
        ...

    @abstractmethod
    def json_to_model(self, json_str: str, model_class: Type, **kwargs) -> Any:
        """Конвертировать JSON строку в Pydantic модель."""
        ...


class IDataValidator(ABC):
    """Интерфейс для валидатора данных (реализация: core/validators.py)."""

    @abstractmethod
    def validate(
        self,
        data: Dict[str, Any],
        model_class: Type,
        strict: bool = False,
    ) -> Tuple[bool, Optional[Any], Optional[str]]:
        """Валидировать данные по модели."""
        ...

    @abstractmethod
    def is_valid(
        self,
        data: Dict[str, Any],
        model_class: Type,
        strict: bool = False,
    ) -> bool:
        """Проверить валидность данных без создания экземпляра."""
        ...

    @abstractmethod
    def get_validation_errors(
        self,
        data: Dict[str, Any],
        model_class: Type,
        strict: bool = False,
    ) -> List[Dict[str, Any]]:
        """Получить список ошибок валидации."""
        ...


# =============================================================================
# Инструменты визуализации и документации (для extensions/)
# =============================================================================

class IVisualizationFormatter(ABC):
    """Интерфейс стратегии визуализации схем."""

    @abstractmethod
    def format(self, schema_name: str, schema_info: Dict[str, Any]) -> str:
        """Форматировать информацию о схеме."""
        ...

    @property
    @abstractmethod
    def format_name(self) -> str:
        """Имя формата (например, 'text', 'html', 'mermaid')."""
        ...


class IDocumentationFormatter(ABC):
    """Интерфейс стратегии форматирования документации схем."""

    @abstractmethod
    def format_schema(
        self,
        schema_name: str,
        schema_info: Dict[str, Any],
        include_examples: bool = True,
    ) -> str:
        """Форматировать документацию для одной схемы."""
        ...

    @abstractmethod
    def format_api_reference(
        self,
        schemas: List[str],
        schema_infos: Dict[str, Dict[str, Any]],
    ) -> str:
        """Форматировать API Reference для всех схем."""
        ...

    @property
    @abstractmethod
    def format_name(self) -> str:
        """Имя формата (например, 'markdown', 'rst', 'html')."""
        ...


class ISchemaVisualizer(ABC):
    """Интерфейс для визуализатора схем."""

    @abstractmethod
    def visualize_schema(
        self,
        schema_name: str,
        format: str = "text",
        include_defaults: bool = True,
        include_types: bool = True,
        include_descriptions: bool = True,
    ) -> str:
        """Визуализировать схему в указанном формате."""
        ...

    @abstractmethod
    def register_formatter(self, formatter: IVisualizationFormatter) -> None:
        """Зарегистрировать новый форматер визуализации."""
        ...

    @abstractmethod
    def list_formats(self) -> List[str]:
        """Получить список доступных форматов."""
        ...


class ISchemaDocumentationGenerator(ABC):
    """Интерфейс для генератора документации схем."""

    @abstractmethod
    def generate_documentation(
        self,
        schema_name: Optional[str] = None,
        format: str = "markdown",
        include_examples: bool = True,
        include_defaults: bool = True,
    ) -> str:
        """Сгенерировать документацию для схемы или всех схем."""
        ...

    @abstractmethod
    def register_formatter(self, formatter: IDocumentationFormatter) -> None:
        """Зарегистрировать новый форматер документации."""
        ...

    @abstractmethod
    def list_formats(self) -> List[str]:
        """Получить список доступных форматов."""
        ...


# =============================================================================
# Расширенные интерфейсы (для extensions/ — зависят от ProcessData)
# =============================================================================

class IStorageManager(ABC):
    """
    Интерфейс для менеджера хранения данных компонентов в ProcessData.

    Реализация живёт в extensions/storage_manager.py.
    Зависит от process_module.ProcessData — поэтому в extensions/.
    """

    @abstractmethod
    def register_manager(
        self,
        manager_model: Any,
        process_name: Optional[str] = None,
    ) -> bool:
        """Зарегистрировать менеджер в ProcessData."""
        ...

    @abstractmethod
    def get_manager_model(
        self,
        manager_name: str,
        manager_type: str,
        process_name: Optional[str] = None,
    ) -> Optional[Any]:
        """Получить модель менеджера из ProcessData."""
        ...

    @abstractmethod
    def update_manager_model(
        self,
        manager_model: Any,
        process_name: Optional[str] = None,
    ) -> bool:
        """Обновить модель менеджера в ProcessData."""
        ...

    @abstractmethod
    def get_manager_config(
        self,
        manager_type: str,
        manager_name: str,
        key: str,
        default: Any = None,
        process_name: Optional[str] = None,
    ) -> Any:
        """Получить конфигурацию менеджера."""
        ...

    @abstractmethod
    def update_manager_config(
        self,
        manager_type: str,
        manager_name: str,
        key: str,
        value: Any,
        process_name: Optional[str] = None,
    ) -> bool:
        """Обновить конфигурацию менеджера."""
        ...

    @abstractmethod
    def remove_manager(
        self,
        manager_name: str,
        manager_type: Optional[str] = None,
        process_name: Optional[str] = None,
    ) -> bool:
        """Удалить менеджера из ProcessData."""
        ...

    @abstractmethod
    def list_managers(
        self,
        process_name: Optional[str] = None,
        manager_type: Optional[str] = None,
    ) -> List[str]:
        """Получить список имен менеджеров."""
        ...


class IVersionManager(ABC):
    """
    Интерфейс для менеджера версий конфигов.

    Реализация живёт в extensions/versioning.py.
    Зависит от ProcessData — поэтому в extensions/.
    """

    @abstractmethod
    def create_version(
        self,
        manager_model: Any,
        comment: Optional[str] = None,
        author: Optional[str] = None,
        tags: Optional[List[str]] = None,
        process_name: Optional[str] = None,
    ) -> int:
        """Создать новую версию модели."""
        ...

    @abstractmethod
    def get_current_version(
        self,
        manager_type: str,
        manager_name: str,
        process_name: Optional[str] = None,
    ) -> int:
        """Получить текущую версию менеджера."""
        ...

    @abstractmethod
    def get_version(
        self,
        manager_type: str,
        manager_name: str,
        version: int,
        process_name: Optional[str] = None,
    ) -> Optional[Any]:
        """Получить модель по версии."""
        ...

    @abstractmethod
    def rollback(
        self,
        manager_type: str,
        manager_name: str,
        target_version: int,
        process_name: Optional[str] = None,
        create_new_version: bool = True,
        comment: Optional[str] = None,
    ) -> bool:
        """Откатиться к указанной версии."""
        ...

    @abstractmethod
    def get_version_history(
        self,
        manager_type: str,
        manager_name: str,
        process_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Получить историю версий."""
        ...

    @abstractmethod
    def compare_versions(
        self,
        manager_type: str,
        manager_name: str,
        version1: int,
        version2: int,
        process_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Сравнить две версии."""
        ...


# =============================================================================
# Backward compatibility aliases (старые имена)
# =============================================================================

# IRegisterStorage -> ISchemaStorage
IRegisterStorage = ISchemaStorage
# IAsyncRegisterStorage -> IAsyncSchemaStorage
IAsyncRegisterStorage = IAsyncSchemaStorage


class ISchemaManager(ABC):
    """
    Backward-compatible интерфейс реестра схем (старое имя до канона ISchemaRegistry).

    Используйте ISchemaRegistry для нового кода.
    Отличие от ISchemaRegistry: методы называются get_schema/has_schema/create_instance.
    """

    @abstractmethod
    def register(self, schema_name: str, schema_class: Type) -> bool: ...

    @abstractmethod
    def get_schema(self, schema_name: str) -> Optional[Type]: ...

    @abstractmethod
    def has_schema(self, schema_name: str) -> bool: ...

    @abstractmethod
    def create_instance(
        self, schema_name: str, data: Optional[Dict[str, Any]] = None, **kwargs
    ) -> Any: ...

    @abstractmethod
    def get_defaults(self, schema_name: str) -> Dict[str, Any]: ...

    @abstractmethod
    def validate(
        self, schema_name: str, data: Dict[str, Any]
    ) -> Tuple[bool, Optional[Any], Optional[str]]: ...

    @abstractmethod
    def list_schemas(self) -> List[str]: ...

    @abstractmethod
    def unregister(self, schema_name: str) -> bool: ...

    @abstractmethod
    def clear(self) -> None: ...
