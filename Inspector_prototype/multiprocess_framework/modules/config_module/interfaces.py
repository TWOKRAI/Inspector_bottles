"""
Публичный контракт config_module.

Единственный файл, от которого разрешено зависеть другим модулям.
"""
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable

from multiprocess_framework.modules.base_manager.interfaces import IBaseManager


@runtime_checkable
class IConfigObserver(Protocol):
    """Протокол подписчика на изменения конфигурации."""

    def __call__(self, key: str, old_value: Any, new_value: Any) -> None: ...


class IConfig(ABC):
    """
    Контракт runtime-контейнера конфигурации.

    Умышленно не включает load() / save() — работа с файлами
    делегируется DataConverter вне этого интерфейса.
    """

    @abstractmethod
    def get(self, key: str, default: Any = None, env_fallback: bool = True) -> Any:
        """Получить значение по dot-notation ключу."""

    @abstractmethod
    def set(self, key: str, value: Any, notify: bool = True) -> "IConfig":
        """Установить значение по dot-notation ключу."""

    @abstractmethod
    def update(self, data: Dict[str, Any]) -> "IConfig":
        """Рекурсивно обновить конфигурацию из словаря."""

    @abstractmethod
    def has(self, key: str) -> bool:
        """Проверить наличие ключа."""

    @abstractmethod
    def remove(self, key: str) -> bool:
        """Удалить ключ. Возвращает True если ключ существовал."""

    @abstractmethod
    def clear(self) -> "IConfig":
        """Очистить все данные."""

    @abstractmethod
    def section(self, section_key: str) -> Any:
        """Вернуть ConfigSection для работы с секцией."""

    @abstractmethod
    def subscribe(
        self,
        callback: Optional[Callable] = None,
        key: str = "*",
    ) -> Any:
        """Подписаться на изменения (можно использовать как декоратор)."""

    @abstractmethod
    def unsubscribe(self, callback: Callable, key: str = "*") -> bool:
        """Отписаться от изменений."""

    @property
    @abstractmethod
    def data(self) -> Dict[str, Any]:
        """Копия всех данных конфигурации."""


class IConfigManager(IBaseManager, ABC):
    """Контракт менеджера конфигураций."""

    @abstractmethod
    def create_config(
        self,
        name: str,
        initial_data: Optional[Dict[str, Any]] = None,
        validation_schema: Optional[Any] = None,
        env_prefix: Optional[str] = None,
    ) -> IConfig:
        """Создать конфигурацию (или вернуть существующую)."""

    @abstractmethod
    def get_config(self, name: str) -> Optional[IConfig]:
        """Получить конфигурацию по имени."""

    @abstractmethod
    def remove_config(self, name: str) -> bool:
        """Удалить конфигурацию."""

    @abstractmethod
    def list_configs(self) -> List[str]:
        """Список имён всех конфигураций."""

    @abstractmethod
    def has_config(self, name: str) -> bool:
        """Проверить наличие конфигурации."""

    @abstractmethod
    def sync_config(self, name: str) -> bool:
        """Сохранить конфигурацию в ConfigStore (Dict at Boundary)."""

    @abstractmethod
    def load_config_from_storage(self, name: str) -> bool:
        """Загрузить конфигурацию из ConfigStore."""
