"""
Публичные контракты (интерфейсы) модуля base_manager.

Используются для:
- Аннотаций типов и статической проверки (mypy, pyright)
- Создания моков в тестах
- Документации ожидаемого поведения

Пример использования в type hints:
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from multiprocess_framework.modules.base_manager.interfaces import IBaseManager
"""

from abc import ABC, abstractmethod
from typing import Any, Optional, Dict, Set, List
from contextlib import contextmanager

# =============================================================================
# IBaseManager
# =============================================================================

class IBaseManager(ABC):
    """
    Контракт базового менеджера.

    Все менеджеры системы наследуют BaseManager, который реализует
    этот интерфейс. Используйте IBaseManager для type hints и проверки
    isinstance() там, где важна принадлежность к иерархии менеджеров.
    """

    # ---- Жизненный цикл ----

    @abstractmethod
    def initialize(self) -> bool:
        """Инициализировать менеджер. True — успех."""

    @abstractmethod
    def shutdown(self) -> bool:
        """Корректно завершить работу. True — успех."""

    # ---- Адаптеры ----

    @abstractmethod
    def attach_adapter(self, adapter: Any, name: Optional[str] = None) -> bool:
        """
        Подключить адаптер.

        Args:
            adapter: Экземпляр адаптера
            name:    Имя адаптера (рекомендуется указывать явно)

        Returns:
            True если подключён успешно
        """

    @abstractmethod
    def get_adapter(self, name: Optional[str] = None) -> Optional[Any]:
        """
        Получить адаптер по имени.

        Returns:
            Адаптер или None
        """

    @abstractmethod
    def has_adapter(self, name: str) -> bool:
        """True если адаптер с таким именем подключён."""

    @abstractmethod
    def list_adapters(self) -> List[str]:
        """Список имён подключённых адаптеров."""

    @abstractmethod
    def detach_adapter(self, name: str) -> bool:
        """Отключить адаптер. True если он был подключён."""

    # ---- Статистика / диагностика ----

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Статистика менеджера."""

    @abstractmethod
    def get_debug_info(self) -> Dict[str, Any]:
        """Подробная диагностическая информация."""


# =============================================================================
# IBaseAdapter
# =============================================================================

class IBaseAdapter(ABC):
    """
    Контракт базового адаптера.

    Адаптер инкапсулирует логику взаимодействия менеджера с процессом
    или внешним ресурсом.
    """

    @abstractmethod
    def setup(self) -> bool:
        """Настроить адаптер. True — успех."""

    @abstractmethod
    def is_initialized(self) -> bool:
        """True если адаптер готов к работе."""


# =============================================================================
# IObservableMixin
# =============================================================================

class IObservableMixin(ABC):
    """
    Контракт ObservableMixin.

    Определяет полный публичный API для наблюдаемости менеджеров:
    регистрация внешних сервисов (logger, stats, error …), управление
    их состоянием и получение диагностики.
    """

    # ---- Управление менеджерами ----

    @abstractmethod
    def register_manager(self, name: str, manager: Any, enabled: bool = True) -> None:
        """Зарегистрировать менеджер под именем name."""

    @abstractmethod
    def unregister_manager(self, name: str) -> None:
        """Удалить менеджер из реестра."""

    @abstractmethod
    def get_manager(self, name: str) -> Optional[Any]:
        """Получить менеджер по имени."""

    @abstractmethod
    def has_manager(self, name: str) -> bool:
        """True если менеджер зарегистрирован."""

    # ---- Состояние ----

    @abstractmethod
    def enable(self, manager_name: str, enabled: bool = True) -> None:
        """Включить или выключить менеджер."""

    @abstractmethod
    def disable(self, manager_name: str) -> None:
        """Выключить менеджер."""

    @abstractmethod
    def is_enabled(self, manager_name: str) -> bool:
        """True если менеджер включён."""

    @abstractmethod
    def get_enabled_managers(self) -> Set[str]:
        """Множество имён включённых менеджеров."""

    @abstractmethod
    def context(self, manager_name: str, enabled: bool = True):
        """Контекстный менеджер для временного изменения состояния."""

    # ---- Конфигурация ----

    @abstractmethod
    def update_config(self, config: Dict[str, Any]) -> None:
        """Обновить конфигурацию."""

    @abstractmethod
    def get_config(self) -> Dict[str, Any]:
        """Текущая конфигурация."""

    @abstractmethod
    def get_state(self) -> Dict[str, Any]:
        """Полный снимок состояния."""


    # ---- Встроенные методы наблюдаемости ----

    @abstractmethod
    def _log(self, level: str, message: str, **kwargs) -> None:
        """Логирование через logger manager."""

    @abstractmethod
    def _log_debug(self, message: str, **kwargs) -> None:
        """Логирование уровня DEBUG."""

    @abstractmethod
    def _log_info(self, message: str, **kwargs) -> None:
        """Логирование уровня INFO."""

    @abstractmethod
    def _log_warning(self, message: str, **kwargs) -> None:
        """Логирование уровня WARNING."""

    @abstractmethod
    def _log_error(self, message: str, **kwargs) -> None:
        """Логирование уровня ERROR."""

    @abstractmethod
    def _log_critical(self, message: str, **kwargs) -> None:
        """Логирование уровня CRITICAL."""

    @abstractmethod
    def _record_metric(
        self, metric_name: str, value: Any = 1,
        tags: Optional[Dict[str, str]] = None
    ) -> None:
        """Запись метрики."""

    @abstractmethod
    def _record_timing(
        self, metric_name: str, duration: float,
        tags: Optional[Dict[str, str]] = None
    ) -> None:
        """Запись времени выполнения."""

    @abstractmethod
    def _track_error(
        self, error: Exception,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Отслеживание ошибки."""
