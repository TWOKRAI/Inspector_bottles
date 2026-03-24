"""
ConfigManager — менеджер множества конфигураций.

Ответственность:
- Создание / получение / удаление объектов Config по имени
- Синхронизация с ConfigStore (SharedResourcesManager) — Dict at Boundary
- Lifecycle: initialize / shutdown

Намеренно НЕ включает:
- StorageManager (удалён — не используется, заменён прямым вызовом config_store)
- EventManager (удалён — бизнес-логика событий остаётся за вызывающим кодом)
"""
from __future__ import annotations

from threading import RLock
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from base_manager import BaseManager, ObservableMixin
from config_module.interfaces import IConfigManager
from config_module.core.config import Config

if TYPE_CHECKING:
    from shared_resources_module.core.shared_resources_manager import SharedResourcesManager


class ConfigManager(BaseManager, ObservableMixin, IConfigManager):
    """
    Менеджер конфигураций.

    Примеры::

        cm = ConfigManager()
        cfg = cm.create_config("app", {"debug": False})
        cfg.set("debug", True)
        cm.sync_config("app")               # → ConfigStore
        cm.load_config_from_storage("app")  # ← ConfigStore
    """

    def __init__(
        self,
        manager_name: str = "ConfigManager",
        shared_resources: Optional["SharedResourcesManager"] = None,
        managers: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        BaseManager.__init__(self, manager_name=manager_name)
        ObservableMixin.__init__(self, managers=managers or {})

        self._shared_resources = shared_resources
        self._configs: Dict[str, Config] = {}
        self._lock = RLock()

    # -------------------------------------------------------------------------
    # Lifecycle (BaseManager)
    # -------------------------------------------------------------------------

    def initialize(self) -> bool:
        try:
            if self._shared_resources:
                self._load_all_from_store()
            self.is_initialized = True
            self._log_info(f"ConfigManager '{self.manager_name}' initialized")
            return True
        except Exception as exc:
            self._log_error(f"ConfigManager initialization failed: {exc}")
            return False

    def shutdown(self) -> bool:
        try:
            if self._shared_resources:
                self._save_all_to_store()
            with self._lock:
                self._configs.clear()
            self.is_initialized = False
            self._log_info("ConfigManager shutdown completed")
            return True
        except Exception as exc:
            self._log_error(f"ConfigManager shutdown error: {exc}")
            return False

    # -------------------------------------------------------------------------
    # IConfigManager — основной API
    # -------------------------------------------------------------------------

    def create_config(
        self,
        name: str,
        initial_data: Optional[Dict[str, Any]] = None,
        validation_schema: Optional[Any] = None,
        env_prefix: Optional[str] = None,
    ) -> Config:
        """
        Создать новую конфигурацию или вернуть существующую.

        Args:
            name: Уникальное имя конфигурации.
            initial_data: Начальные данные.
            validation_schema: Зарезервировано для будущего использования.
            env_prefix: Префикс env-переменных для fallback.
        """
        with self._lock:
            if name in self._configs:
                self._log_warning(f"Config '{name}' already exists — returning existing")
                return self._configs[name]
            config = Config(initial_data=initial_data, env_prefix=env_prefix)
            self._configs[name] = config
            self._log_info(f"Config '{name}' created")
            return config

    def get_config(self, name: str) -> Optional[Config]:
        """Получить конфигурацию по имени."""
        with self._lock:
            return self._configs.get(name)

    def remove_config(self, name: str) -> bool:
        """Удалить конфигурацию. Возвращает True если конфигурация существовала."""
        with self._lock:
            if name not in self._configs:
                return False
            del self._configs[name]
            self._log_info(f"Config '{name}' removed")
            return True

    def list_configs(self) -> List[str]:
        """Список имён всех конфигураций."""
        with self._lock:
            return list(self._configs.keys())

    def has_config(self, name: str) -> bool:
        """Проверить наличие конфигурации."""
        with self._lock:
            return name in self._configs

    def get_all_configs(self) -> Dict[str, Config]:
        """Копия словаря {name: Config}."""
        with self._lock:
            return dict(self._configs)

    # -------------------------------------------------------------------------
    # Синхронизация с ConfigStore (SharedResourcesManager)
    # -------------------------------------------------------------------------

    def sync_config(self, name: str) -> bool:
        """
        Сохранить конфигурацию в ConfigStore (Dict at Boundary).

        Returns:
            True при успехе.
        """
        config = self._configs.get(name)
        if config is None:
            self._log_error(f"sync_config: config '{name}' not found")
            return False
        if not self._shared_resources:
            self._log_warning("sync_config: shared_resources not available")
            return False
        try:
            self._shared_resources.config_store.store(name, config.data)
            return True
        except Exception as exc:
            self._log_error(f"sync_config '{name}' failed: {exc}")
            return False

    def load_config_from_storage(self, name: str) -> bool:
        """
        Загрузить конфигурацию из ConfigStore.

        Returns:
            True при успехе.
        """
        if not self._shared_resources:
            self._log_warning("load_config_from_storage: shared_resources not available")
            return False
        try:
            data = self._shared_resources.config_store.get(name)
            if data is None:
                return False
            with self._lock:
                if name in self._configs:
                    self._configs[name].update(data)
                else:
                    self._configs[name] = Config(initial_data=data)
            return True
        except Exception as exc:
            self._log_error(f"load_config_from_storage '{name}' failed: {exc}")
            return False

    # -------------------------------------------------------------------------
    # Внутренние методы
    # -------------------------------------------------------------------------

    def _save_all_to_store(self) -> None:
        for name in list(self._configs):
            self.sync_config(name)

    def _load_all_from_store(self) -> None:
        if not self._shared_resources:
            return
        try:
            names = self._shared_resources.config_store.list_keys()
            for name in names:
                self.load_config_from_storage(name)
        except Exception:
            pass
