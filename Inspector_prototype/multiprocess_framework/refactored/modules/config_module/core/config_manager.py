"""
ConfigManager - менеджер для управления множеством конфигураций.

Это менеджер (наследуется от BaseManager), который управляет множеством объектов Config.
Каждый Config - это контейнер данных для одной конфигурации.

Архитектура:
- Config (base_config.py): контейнер данных для ОДНОЙ конфигурации
- ConfigManager (config_manager.py): менеджер для управления МНОЖЕСТВОМ Config объектов

Интеграция с системой:
- BaseManager: единообразие со всеми менеджерами
- SharedResourcesManager: хранение в ProcessData
- EventManager: синхронизация между процессами
- StorageManager: работа с ProcessData

Предоставляет централизованное управление конфигурациями с поддержкой:
- Хранения в ProcessData через StorageManager
- Синхронизации через EventManager (автоматическая + ручная)
- Валидации через Pydantic схемы
- Версионирования (опционально)
"""
from typing import Dict, Any, Optional, Union, Type, TYPE_CHECKING
from pathlib import Path
from threading import RLock
import time

if TYPE_CHECKING:
    from multiprocessing import Process
    from pydantic import BaseModel

from ...base_manager import BaseManager, ObservableMixin
from ...base_manager.interfaces import IBaseManager
from ..interfaces import IConfigManager, IConfig
from .base_config import Config  # Импорт из того же пакета core/
from ...data_schema_module.storage.storage_manager import StorageManager
from ...shared_resources_module.events.event_manager import EventManager, EventType

# Ленивый импорт SharedResourcesManager — избегаем циклической зависимости
# (shared_resources -> process_module -> config -> config_manager -> shared_resources)
if TYPE_CHECKING:
    from ...shared_resources_module.core.shared_resources_manager import SharedResourcesManager


class ConfigManager(BaseManager, ObservableMixin, IConfigManager):
    """
    Менеджер конфигураций с интеграцией всех модулей системы.
    
    Особенности:
    - Наследуется от BaseManager для единообразия
    - Использует ObservableMixin для логирования и метрик
    - Хранит конфигурации в ProcessData через StorageManager
    - Синхронизирует изменения через EventManager
    - Поддерживает валидацию через Pydantic схемы
    - Опциональное версионирование через VersionManager
    
    Attributes:
        _configs: Словарь всех конфигураций {name: Config}
        _lock: Блокировка для потокобезопасности
        _storage_manager: StorageManager для работы с ProcessData
        _event_manager: EventManager для синхронизации
        _shared_resources: SharedResourcesManager для доступа к ProcessData
        _auto_sync: Автоматическая синхронизация при изменениях
        _config_storage_key: Ключ для хранения конфигураций в ProcessData.custom
    """
    
    # Ключ для хранения конфигураций в ProcessData.custom
    CONFIG_STORAGE_KEY = 'configurations'
    
    def __init__(
        self,
        manager_name: str = "ConfigManager",
        process: Optional["Process"] = None,
        shared_resources: Optional["SharedResourcesManager"] = None,
        event_manager: Optional[EventManager] = None,
        storage_manager: Optional[StorageManager] = None,
        auto_sync: bool = True,
        managers: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
        enable_logging: bool = True,
        enable_error_tracking: bool = True,
        enable_statistics: bool = True,
        **kwargs
    ):
        """
        Инициализация ConfigManager.
        
        Args:
            manager_name: Имя менеджера
            process: Ссылка на родительский процесс
            shared_resources: SharedResourcesManager для доступа к ProcessData
            event_manager: EventManager для синхронизации (если None, создается автоматически)
            storage_manager: StorageManager для работы с ProcessData (если None, создается автоматически)
            auto_sync: Автоматическая синхронизация при изменениях
            managers: Словарь менеджеров для ObservableMixin
            config: Конфигурация для ObservableMixin
            enable_logging: Включить логирование
            enable_error_tracking: Включить отслеживание ошибок
            enable_statistics: Включить статистику
            **kwargs: Дополнительные параметры
        """
        # Инициализация BaseManager
        BaseManager.__init__(self, manager_name=manager_name, process=process)
        
        # Подготовка менеджеров для ObservableMixin
        if managers is None:
            managers = {}
        
        if config is None:
            config = {
                'logger': enable_logging,
                'error': enable_error_tracking,
                'statistics': enable_statistics
            }
        
        # Инициализация ObservableMixin
        ObservableMixin.__init__(
            self,
            managers=managers,
            config=config,
            auto_proxy=True
        )
        
        # Сохраняем зависимости
        self._shared_resources = shared_resources
        self._auto_sync = auto_sync
        
        # Создаем или используем существующие менеджеры
        if storage_manager:
            self._storage_manager = storage_manager
        else:
            self._storage_manager = StorageManager(shared_resources=shared_resources)
        
        if event_manager:
            self._event_manager = event_manager
        elif shared_resources:
            # Используем EventManager из shared_resources если доступен
            self._event_manager = shared_resources.event_manager
        else:
            self._event_manager = None
        
        # Хранилище конфигураций
        self._configs: Dict[str, Config] = {}
        self._lock = RLock()
        
        # Метаданные конфигураций (схемы валидации, пути к файлам и т.д.)
        self._config_metadata: Dict[str, Dict[str, Any]] = {}
        
        # Подписка на события конфигураций
        self._setup_config_subscriptions()
    
    def _setup_config_subscriptions(self):
        """Настроить подписки на изменения конфигураций для автоматической синхронизации."""
        # Будет вызываться при создании/изменении конфигураций
        pass
    
    # ========================================================================
    # РЕАЛИЗАЦИЯ BaseManager - ЖИЗНЕННЫЙ ЦИКЛ
    # ========================================================================
    
    def initialize(self) -> bool:
        """
        Инициализация ConfigManager.
        
        Загружает конфигурации из ProcessData если доступен shared_resources.
        
        Returns:
            bool: True если инициализация успешна
        """
        try:
            # Загружаем конфигурации из ProcessData если доступен shared_resources
            if self._shared_resources:
                self._load_all_configs_from_storage()
            
            self.is_initialized = True
            self._log_info(f"ConfigManager '{self.manager_name}' initialized")
            return True
        except Exception as e:
            self._log_error(f"Failed to initialize ConfigManager: {e}")
            return False
    
    def shutdown(self) -> bool:
        """
        Завершение работы ConfigManager.
        
        Сохраняет все конфигурации в ProcessData перед завершением.
        
        Returns:
            bool: True если завершение успешно
        """
        try:
            # Сохраняем все конфигурации в ProcessData
            if self._shared_resources:
                self._save_all_configs_to_storage()
            
            # Очищаем подписки
            for config in self._configs.values():
                config.unsubscribe(self._on_config_change, "*")
            
            self._configs.clear()
            self._config_metadata.clear()
            
            self.is_initialized = False
            self._log_info("ConfigManager shutdown completed")
            return True
        except Exception as e:
            self._log_error(f"Error during ConfigManager shutdown: {e}")
            return False
    
    # ========================================================================
    # РЕАЛИЗАЦИЯ IConfigManager - ОСНОВНОЙ API
    # ========================================================================
    
    def get_config(self, name: str) -> Optional[Config]:
        """
        Получить конфигурацию по имени.
        
        Args:
            name: Имя конфигурации
        
        Returns:
            Config или None если конфигурация не найдена
        """
        with self._lock:
            return self._configs.get(name)
    
    def create_config(
        self,
        name: str,
        initial_data: Optional[Dict[str, Any]] = None,
        file_path: Optional[Union[str, Path]] = None,
        validation_schema: Optional[Type["BaseModel"]] = None,
        validate_on_set: bool = False,
        env_prefix: Optional[str] = None,
        auto_sync: Optional[bool] = None
    ) -> Config:
        """
        Создать новую конфигурацию.
        
        Args:
            name: Имя конфигурации
            initial_data: Начальные данные конфигурации
            file_path: Путь к файлу конфигурации для автоматической загрузки
            validation_schema: Опциональная Pydantic схема для валидации
            validate_on_set: Валидировать ли данные при установке
            env_prefix: Префикс для переменных окружения
            auto_sync: Автоматическая синхронизация для этой конфигурации (если None, используется общая настройка)
        
        Returns:
            Созданный объект Config
        """
        with self._lock:
            if name in self._configs:
                self._log_warning(f"Config '{name}' already exists, returning existing config")
                return self._configs[name]
            
            # Создаем конфигурацию
            config = Config(
                initial_data=initial_data,
                env_prefix=env_prefix,
                file_path=file_path,
                validation_schema=validation_schema,
                validate_on_set=validate_on_set
            )
            
            # Сохраняем метаданные
            self._config_metadata[name] = {
                'validation_schema': validation_schema,
                'validate_on_set': validate_on_set,
                'file_path': str(file_path) if file_path else None,
                'env_prefix': env_prefix,
                'auto_sync': auto_sync if auto_sync is not None else self._auto_sync,
                'created_at': time.time()
            }
            
            # Подписываемся на изменения для автоматической синхронизации
            if self._config_metadata[name]['auto_sync']:
                config.subscribe(self._on_config_change, "*")
            
            self._configs[name] = config
            
            # Сохраняем в ProcessData если доступен shared_resources
            if self._shared_resources:
                self._save_config_to_storage(name)
            
            # Отправляем событие о создании конфигурации
            if self._event_manager:
                self._event_manager.emit_event(
                    EventType.CONFIG_UPDATED,
                    config_name=name,
                    action='created'
                )
            
            self._log_info(f"Config '{name}' created")
            return config
    
    def remove_config(self, name: str) -> bool:
        """
        Удалить конфигурацию.
        
        Args:
            name: Имя конфигурации
        
        Returns:
            True если конфигурация была удалена
        """
        with self._lock:
            if name not in self._configs:
                return False
            
            # Отписываемся от изменений
            config = self._configs[name]
            config.unsubscribe(self._on_config_change, "*")
            
            # Удаляем из ProcessData
            if self._shared_resources:
                self._remove_config_from_storage(name)
            
            # Отправляем событие об удалении конфигурации
            if self._event_manager:
                self._event_manager.emit_event(
                    EventType.CONFIG_UPDATED,
                    config_name=name,
                    action='removed'
                )
            
            # Удаляем конфигурацию
            del self._configs[name]
            del self._config_metadata[name]
            
            self._log_info(f"Config '{name}' removed")
            return True
    
    def list_configs(self) -> list[str]:
        """
        Получить список всех конфигураций.
        
        Returns:
            Список имен конфигураций
        """
        with self._lock:
            return list(self._configs.keys())
    
    def sync_config(self, name: str, process_name: Optional[str] = None) -> bool:
        """
        Синхронизировать конфигурацию с ProcessData (ручная синхронизация).
        
        Args:
            name: Имя конфигурации
            process_name: Имя процесса (если None, используется текущий процесс)
        
        Returns:
            True если синхронизация успешна
        """
        with self._lock:
            if name not in self._configs:
                self._log_error(f"Config '{name}' not found for sync")
                return False
            
            if not self._shared_resources:
                self._log_warning("SharedResourcesManager not available, cannot sync")
                return False
            
            return self._save_config_to_storage(name, process_name)
    
    def load_config_from_storage(self, name: str, process_name: Optional[str] = None) -> bool:
        """
        Загрузить конфигурацию из ProcessData.
        
        Args:
            name: Имя конфигурации
            process_name: Имя процесса (если None, используется текущий процесс)
        
        Returns:
            True если загрузка успешна
        """
        with self._lock:
            if not self._shared_resources:
                self._log_warning("SharedResourcesManager not available, cannot load from storage")
                return False
            
            return self._load_config_from_storage(name, process_name)
    
    # ========================================================================
    # РАБОТА С ХРАНИЛИЩЕМ (ProcessData через StorageManager)
    # ========================================================================
    
    def _save_config_to_storage(self, name: str, process_name: Optional[str] = None) -> bool:
        """Сохранить конфигурацию в ProcessData."""
        try:
            config = self._configs.get(name)
            if not config:
                return False
            
            # Получаем ProcessData
            if process_name:
                process_data = self._shared_resources.get_process_data(process_name)
            else:
                # Используем текущий процесс если возможно
                current_process_name = getattr(self._shared_resources, 'current_process_name', None)
                if current_process_name:
                    process_data = self._shared_resources.get_process_data(current_process_name)
                else:
                    # Берем первый доступный процесс или создаем новый
                    all_processes = self._shared_resources.get_all_process_data()
                    if all_processes:
                        process_data = list(all_processes.values())[0]
                    else:
                        self._log_warning("No process data available for saving config")
                        return False
            
            if not process_data:
                return False
            
            # Инициализируем структуру если её нет
            if self.CONFIG_STORAGE_KEY not in process_data.custom:
                process_data.custom[self.CONFIG_STORAGE_KEY] = {}
            
            # Сохраняем конфигурацию
            configs_storage = process_data.custom[self.CONFIG_STORAGE_KEY]
            configs_storage[name] = {
                'data': config.data,
                'metadata': self._config_metadata.get(name, {}),
                'updated_at': time.time()
            }
            
            # Обновляем timestamp ProcessData
            process_data.update_timestamp()
            
            return True
        except Exception as e:
            self._log_error(f"Failed to save config '{name}' to storage: {e}")
            return False
    
    def _load_config_from_storage(self, name: str, process_name: Optional[str] = None) -> bool:
        """Загрузить конфигурацию из ProcessData."""
        try:
            # Получаем ProcessData
            if process_name:
                process_data = self._shared_resources.get_process_data(process_name)
            else:
                # Используем текущий процесс если возможно
                current_process_name = getattr(self._shared_resources, 'current_process_name', None)
                if current_process_name:
                    process_data = self._shared_resources.get_process_data(current_process_name)
                else:
                    # Берем первый доступный процесс
                    all_processes = self._shared_resources.get_all_process_data()
                    if all_processes:
                        process_data = list(all_processes.values())[0]
                    else:
                        return False
            
            if not process_data:
                return False
            
            # Получаем конфигурацию из хранилища
            configs_storage = process_data.custom.get(self.CONFIG_STORAGE_KEY, {})
            config_data = configs_storage.get(name)
            
            if not config_data:
                return False
            
            # Восстанавливаем метаданные
            metadata = config_data.get('metadata', {})
            self._config_metadata[name] = metadata
            
            # Создаем или обновляем конфигурацию
            if name in self._configs:
                # Обновляем существующую конфигурацию
                config = self._configs[name]
                config.update(config_data['data'], prefix="")
            else:
                # Создаем новую конфигурацию
                config = Config(
                    initial_data=config_data['data'],
                    env_prefix=metadata.get('env_prefix'),
                    validation_schema=metadata.get('validation_schema'),
                    validate_on_set=metadata.get('validate_on_set', False)
                )
                
                # Подписываемся на изменения
                if metadata.get('auto_sync', self._auto_sync):
                    config.subscribe(self._on_config_change, "*")
                
                self._configs[name] = config
            
            return True
        except Exception as e:
            self._log_error(f"Failed to load config '{name}' from storage: {e}")
            return False
    
    def _remove_config_from_storage(self, name: str, process_name: Optional[str] = None) -> bool:
        """Удалить конфигурацию из ProcessData."""
        try:
            # Получаем ProcessData
            if process_name:
                process_data = self._shared_resources.get_process_data(process_name)
            else:
                current_process_name = getattr(self._shared_resources, 'current_process_name', None)
                if current_process_name:
                    process_data = self._shared_resources.get_process_data(current_process_name)
                else:
                    all_processes = self._shared_resources.get_all_process_data()
                    if all_processes:
                        process_data = list(all_processes.values())[0]
                    else:
                        return False
            
            if not process_data:
                return False
            
            # Удаляем конфигурацию из хранилища
            configs_storage = process_data.custom.get(self.CONFIG_STORAGE_KEY, {})
            if name in configs_storage:
                del configs_storage[name]
                process_data.update_timestamp()
                return True
            
            return False
        except Exception as e:
            self._log_error(f"Failed to remove config '{name}' from storage: {e}")
            return False
    
    def _save_all_configs_to_storage(self):
        """Сохранить все конфигурации в ProcessData."""
        for name in self._configs.keys():
            self._save_config_to_storage(name)
    
    def _load_all_configs_from_storage(self):
        """Загрузить все конфигурации из ProcessData."""
        if not self._shared_resources:
            return
        
        # Получаем все ProcessData
        all_processes = self._shared_resources.get_all_process_data()
        if not all_processes:
            return
        
        # Загружаем конфигурации из первого доступного процесса
        # В реальном приложении можно загружать из всех процессов и объединять
        process_data = list(all_processes.values())[0]
        configs_storage = process_data.custom.get(self.CONFIG_STORAGE_KEY, {})
        
        for name in configs_storage.keys():
            self._load_config_from_storage(name)
    
    # ========================================================================
    # СИНХРОНИЗАЦИЯ ЧЕРЕЗ EventManager
    # ========================================================================
    
    def _on_config_change(self, key: str, old_value: Any, new_value: Any):
        """
        Callback для автоматической синхронизации при изменении конфигурации.
        
        Args:
            key: Ключ который изменился
            old_value: Старое значение
            new_value: Новое значение
        """
        if not self._event_manager:
            return
        
        # Находим конфигурацию которая изменилась
        # (это упрощенная версия, в реальности нужно отслеживать какая конфигурация изменилась)
        for name, config in self._configs.items():
            if config.has(key) or key == "*":
                # Сохраняем в ProcessData
                self._save_config_to_storage(name)
                
                # Отправляем событие
                self._event_manager.emit_event(
                    EventType.CONFIG_UPDATED,
                    config_name=name,
                    key=key,
                    action='updated'
                )
                break
    
    # ========================================================================
    # ДОПОЛНИТЕЛЬНЫЕ МЕТОДЫ
    # ========================================================================
    
    def get_all_configs(self) -> Dict[str, Config]:
        """Получить все конфигурации."""
        with self._lock:
            return self._configs.copy()
    
    def has_config(self, name: str) -> bool:
        """Проверить наличие конфигурации."""
        with self._lock:
            return name in self._configs
    
    def get_config_metadata(self, name: str) -> Optional[Dict[str, Any]]:
        """Получить метаданные конфигурации."""
        with self._lock:
            return self._config_metadata.get(name)
    
    def set_auto_sync(self, name: str, auto_sync: bool) -> bool:
        """Установить автоматическую синхронизацию для конфигурации."""
        with self._lock:
            if name not in self._configs:
                return False
            
            config = self._configs[name]
            metadata = self._config_metadata.get(name, {})
            metadata['auto_sync'] = auto_sync
            
            if auto_sync:
                config.subscribe(self._on_config_change, "*")
            else:
                config.unsubscribe(self._on_config_change, "*")
            
            return True

