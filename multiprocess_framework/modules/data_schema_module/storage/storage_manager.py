"""
Менеджер хранения данных компонентов.

Объединяет функциональность DataManager и ProcessDataContainer.
Управляет хранением данных менеджеров и ДНК компонентов в ProcessData.
"""

from typing import Dict, Any, Optional, List, TYPE_CHECKING
from threading import RLock

if TYPE_CHECKING:
    # Импорты для type checking - опциональные зависимости
    try:
        from ...process_module.state.process_data import ProcessData
    except ImportError:
        try:
            from ...process_module.process_data import ProcessData
        except ImportError:
            ProcessData = Any  # type: ignore

    try:
        from ...shared_resources_module.core.shared_resources_manager import SharedResourcesManager
    except ImportError:
        SharedResourcesManager = Any  # type: ignore

from ..registry.schema_registry import SchemaManager
from ..models.base import BaseManagerModel
from .interfaces import IStorageManager
from ..core.helpers import get_nested_value, set_nested_value

# Опциональный импорт для ДНК
try:
    from ..models.dna import ComponentDNA
    _has_dna = True
except ImportError:
    ComponentDNA = None  # type: ignore
    _has_dna = False


class StorageManager(IStorageManager):
    """
    Менеджер хранения данных компонентов.
    
    Управляет данными менеджеров и ДНК компонентов в ProcessData используя
    гибридный подход: dict в ProcessData, Pydantic модели в коде.
    """
    
    _instance: Optional['StorageManager'] = None
    _lock = RLock()
    
    # Ключи для хранения в ProcessData.custom
    MANAGERS_KEY = 'component_managers'  # {manager_type: {manager_name: dict}}
    MANAGERS_CONFIG_KEY = 'component_managers_config'  # денормализованный срез конфигов
    DNA_KEY = 'component_dnas'  # {component_type: {component_name: dict}}
    
    def __init__(self, shared_resources: Optional[Any] = None):
        """Инициализация менеджера хранения."""
        self.shared_resources = shared_resources
        self.schema_registry = SchemaManager.get_instance()
    
    @classmethod
    def get_instance(
        cls,
        shared_resources: Optional[Any] = None
    ) -> 'StorageManager':
        """Получить глобальный экземпляр (Singleton)."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(shared_resources)
        return cls._instance
    
    def _resolve_process_name(self, process_name: Optional[str]) -> Optional[str]:
        """Автоопределение имени процесса, если возможно."""
        if process_name:
            return process_name
        if self.shared_resources:
            return getattr(self.shared_resources, "current_process_name", None)
        return None

    def _get_process_data(self, process_name: Optional[str] = None) -> Optional[Any]:
        """Получить ProcessData процесса."""
        try:
            from ...process_module.state.process_data import ProcessData
        except ImportError:
            ProcessData = Any  # type: ignore
        
        if not self.shared_resources:
            return None
        
        resolved_name = self._resolve_process_name(process_name)
        if resolved_name is None:
            return None
        
        return self.shared_resources.get_process_data(resolved_name)
    
    # ========================================================================
    # Методы для работы с менеджерами
    # ========================================================================
    
    def register_manager(
        self,
        manager_model: BaseManagerModel,
        process_name: Optional[str] = None
    ) -> bool:
        """
        Зарегистрировать менеджер в ProcessData.
        
        Сохраняет модель как dict в ProcessData.custom для сериализации.
        
        Args:
            manager_model: Pydantic модель менеджера
            process_name: Имя процесса (опционально)
            
        Returns:
            True если регистрация успешна
        """
        process_data = self._get_process_data(process_name)
        if not process_data:
            return False
        
        # Инициализируем структуру если её нет
        if self.MANAGERS_KEY not in process_data.custom:
            process_data.custom[self.MANAGERS_KEY] = {}
        if self.MANAGERS_CONFIG_KEY not in process_data.custom:
            process_data.custom[self.MANAGERS_CONFIG_KEY] = {}
        
        managers = process_data.custom[self.MANAGERS_KEY]
        configs = process_data.custom[self.MANAGERS_CONFIG_KEY]
        manager_type = manager_model.component_class
        
        # Инициализируем тип если его нет
        if manager_type not in managers:
            managers[manager_type] = {}
        if manager_type not in configs:
            configs[manager_type] = {}
        
        # Сохраняем как dict (Pydantic модель сериализуется)
        managers[manager_type][manager_model.name] = manager_model.model_dump()
        # Кэшируем конфиг отдельно для быстрого доступа
        configs[manager_type][manager_model.name] = manager_model.config
        
        # Обновляем timestamp ProcessData
        process_data.update_timestamp()
        return True
    
    def get_manager_model(
        self,
        manager_name: str,
        manager_type: str,
        process_name: Optional[str] = None
    ) -> Optional[BaseManagerModel]:
        """
        Получить модель менеджера из ProcessData.
        
        Восстанавливает Pydantic модель из dict.
        
        Args:
            manager_name: Имя менеджера
            manager_type: Тип менеджера (имя класса)
            process_name: Имя процесса (опционально)
            
        Returns:
            Pydantic модель менеджера или None
        """
        process_data = self._get_process_data(process_name)
        if not process_data:
            return None
        
        managers = process_data.custom.get(self.MANAGERS_KEY, {})
        manager_dict = managers.get(manager_type, {}).get(manager_name)
        
        if not manager_dict:
            return None
        
        # Восстанавливаем Pydantic модель из dict
        schema = self.schema_registry.get_schema(manager_type)
        if schema:
            return schema(**manager_dict)
        
        # Если схемы нет, используем BaseManagerModel
        return BaseManagerModel(**manager_dict)
    
    def update_manager_model(
        self,
        manager_model: BaseManagerModel,
        process_name: Optional[str] = None
    ) -> bool:
        """Обновить модель менеджера в ProcessData."""
        return self.register_manager(manager_model, process_name)
    
    def get_manager_config(
        self,
        manager_type: str,
        manager_name: str,
        key: str,
        default: Any = None,
        process_name: Optional[str] = None
    ) -> Any:
        """
        Получить конфигурацию менеджера.
        
        Args:
            manager_type: Тип менеджера
            manager_name: Имя менеджера
            key: Ключ конфигурации (поддерживает точечную нотацию)
            default: Значение по умолчанию
            process_name: Имя процесса (опционально)
            
        Returns:
            Значение конфигурации или default
        """
        process_data = self._get_process_data(process_name)
        # Быстрый путь через кэш конфигов
        if process_data:
            configs = process_data.custom.get(self.MANAGERS_CONFIG_KEY, {})
            cached = get_nested_value(configs.get(manager_type, {}).get(manager_name, {}), key, None)
            if cached is not None:
                return cached

        manager_model = self.get_manager_model(manager_name, manager_type, process_name)
        if not manager_model:
            return default
        
        return get_nested_value(manager_model.config, key, default)
    
    def update_manager_config(
        self,
        manager_type: str,
        manager_name: str,
        key: str,
        value: Any,
        process_name: Optional[str] = None
    ) -> bool:
        """Обновить конфигурацию менеджера."""
        manager_model = self.get_manager_model(manager_name, manager_type, process_name)
        if not manager_model:
            return False
        
        # Обновляем значение
        set_nested_value(manager_model.config, key, value)
        manager_model.update_timestamp()
        
        # Сохраняем обратно в ProcessData
        result = self.update_manager_model(manager_model, process_name)

        # Обновляем кэш конфигов
        process_data = self._get_process_data(process_name)
        if process_data:
            if self.MANAGERS_CONFIG_KEY not in process_data.custom:
                process_data.custom[self.MANAGERS_CONFIG_KEY] = {}
            configs = process_data.custom[self.MANAGERS_CONFIG_KEY]
            if manager_type not in configs:
                configs[manager_type] = {}
            configs[manager_type][manager_name] = manager_model.config
            process_data.update_timestamp()

        return result
    
    def remove_manager(
        self,
        manager_name: str,
        manager_type: Optional[str] = None,
        process_name: Optional[str] = None
    ) -> bool:
        """Удалить менеджера из ProcessData."""
        process_data = self._get_process_data(process_name)
        if not process_data:
            return False
        
        managers = process_data.custom.get(self.MANAGERS_KEY, {})
        
        if manager_type:
            if manager_type in managers and manager_name in managers[manager_type]:
                del managers[manager_type][manager_name]
                if not managers[manager_type]:
                    del managers[manager_type]
                process_data.update_timestamp()
                return True
        else:
            # Удаляем из всех типов
            removed = False
            for managers_by_type in list(managers.values()):
                if manager_name in managers_by_type:
                    del managers_by_type[manager_name]
                    removed = True
            
            if removed:
                managers = {k: v for k, v in managers.items() if v}
                process_data.custom[self.MANAGERS_KEY] = managers
                process_data.update_timestamp()
                return True
        
        return False
    
    def list_managers(
        self,
        process_name: Optional[str] = None,
        manager_type: Optional[str] = None
    ) -> List[str]:
        """Получить список имен менеджеров."""
        process_data = self._get_process_data(process_name)
        if not process_data:
            return []
        
        managers = process_data.custom.get(self.MANAGERS_KEY, {})
        
        if manager_type:
            return list(managers.get(manager_type, {}).keys())
        
        # Все менеджеры
        result = []
        for managers_by_type in managers.values():
            result.extend(managers_by_type.keys())
        return result
    
    # ========================================================================
    # Методы для работы с ДНК компонентов (опционально)
    # ========================================================================
    
    def register_dna(self, dna: 'ComponentDNA', process_name: Optional[str] = None) -> bool:
        """
        Зарегистрировать ДНК компонента в ProcessData.
        
        Args:
            dna: ComponentDNA компонента
            process_name: Имя процесса (опционально)
            
        Returns:
            True если регистрация успешна
        """
        if not _has_dna:
            return False
        
        process_data = self._get_process_data(process_name)
        if not process_data:
            return False
        
        if self.DNA_KEY not in process_data.custom:
            process_data.custom[self.DNA_KEY] = {}
        
        dnas = process_data.custom[self.DNA_KEY]
        component_type = dna.component_type.value
        
        if component_type not in dnas:
            dnas[component_type] = {}
        
        # Сохраняем как dict для сериализации
        dnas[component_type][dna.name] = dna.model_dump()
        
        # Обновляем timestamp ProcessData
        process_data.update_timestamp()
        return True
    
    def get_dna(
        self,
        component_name: str,
        component_type: Optional[str] = None,
        process_name: Optional[str] = None
    ) -> Optional['ComponentDNA']:
        """
        Получить ДНК компонента из ProcessData.
        
        Args:
            component_name: Имя компонента
            component_type: Тип компонента (опционально)
            process_name: Имя процесса (опционально)
            
        Returns:
            ComponentDNA или None
        """
        if not _has_dna:
            return None
        
        process_data = self._get_process_data(process_name)
        if not process_data:
            return None
        
        dnas = process_data.custom.get(self.DNA_KEY, {})
        
        if component_type:
            if component_type in dnas and component_name in dnas[component_type]:
                dna_data = dnas[component_type][component_name]
                return ComponentDNA(**dna_data)
        else:
            # Поиск по всем типам
            for type_dnas in dnas.values():
                if component_name in type_dnas:
                    dna_data = type_dnas[component_name]
                    return ComponentDNA(**dna_data)
        
        return None
    
    def list_dnas(
        self,
        component_type: Optional[str] = None,
        process_name: Optional[str] = None
    ) -> List['ComponentDNA']:
        """
        Получить список всех ДНК компонентов.
        
        Args:
            component_type: Фильтр по типу компонента
            process_name: Имя процесса (опционально)
            
        Returns:
            Список ComponentDNA
        """
        if not _has_dna:
            return []
        
        process_data = self._get_process_data(process_name)
        if not process_data:
            return []
        
        dnas = process_data.custom.get(self.DNA_KEY, {})
        result = []
        
        if component_type:
            if component_type in dnas:
                for dna_data in dnas[component_type].values():
                    result.append(ComponentDNA(**dna_data))
        else:
            for type_dnas in dnas.values():
                for dna_data in type_dnas.values():
                    result.append(ComponentDNA(**dna_data))
        
        return result
    
    def remove_dna(
        self,
        component_name: str,
        component_type: Optional[str] = None,
        process_name: Optional[str] = None
    ) -> bool:
        """Удалить ДНК компонента из ProcessData."""
        if not _has_dna:
            return False
        
        process_data = self._get_process_data(process_name)
        if not process_data:
            return False
        
        dnas = process_data.custom.get(self.DNA_KEY, {})
        
        if component_type:
            if component_type in dnas and component_name in dnas[component_type]:
                del dnas[component_type][component_name]
                process_data.update_timestamp()
                return True
        else:
            for type_dnas in dnas.values():
                if component_name in type_dnas:
                    del type_dnas[component_name]
                    process_data.update_timestamp()
                    return True
        
        return False

