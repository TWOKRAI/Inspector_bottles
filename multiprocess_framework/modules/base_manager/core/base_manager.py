"""
BaseManager — абстрактный базовый класс для всех менеджеров системы.
"""

from typing import Dict, Any, Optional, List
from abc import abstractmethod

from ..interfaces import IBaseManager
from ..utils.name_utils import get_adapter_name_from_class


class BaseManager(IBaseManager):
    """
    Абстрактный базовый класс для всех менеджеров системы.

    Реализует контракт IBaseManager и предоставляет:
    - Управление жизненным циклом (initialize / shutdown)
    - Подключение адаптеров (attach_adapter / get_adapter / detach_adapter)
    - Диагностику (get_stats / get_debug_info)

    Типичное использование совместно с ObservableMixin:

        class LoggerManager(BaseManager, ObservableMixin):
            def __init__(self, name, logger=None):
                BaseManager.__init__(self, name)
                ObservableMixin.__init__(self, managers={'logger': logger})

            def initialize(self) -> bool:
                self.is_initialized = True
                return True

            def shutdown(self) -> bool:
                self.is_initialized = False
                return True

    Attributes:
        manager_name (str):      Уникальное имя менеджера
        process (Optional[Any]): Ссылка на родительский процесс (если есть)
        is_initialized (bool):   Флаг инициализации
    """

    def __init__(self, manager_name: str, process: Optional[Any] = None):
        """
        Args:
            manager_name: Уникальное имя менеджера
            process:      Ссылка на родительский процесс
        """
        self.manager_name = manager_name
        self.process = process
        self.is_initialized = False
        self._adapters: Dict[str, Any] = {}

    # =========================================================================
    # ПУБЛИЧНЫЙ API — ЖИЗНЕННЫЙ ЦИКЛ (abstractmethod из IBaseManager)
    # =========================================================================

    @abstractmethod
    def initialize(self) -> bool:
        """
        Инициализация менеджера. Реализуется в подклассах.

        Returns:
            True если инициализация успешна
        """

    @abstractmethod
    def shutdown(self) -> bool:
        """
        Корректное завершение работы менеджера. Реализуется в подклассах.

        Returns:
            True если завершение успешно
        """

    # =========================================================================
    # ПУБЛИЧНЫЙ API — УПРАВЛЕНИЕ АДАПТЕРАМИ
    # =========================================================================

    def attach_adapter(self, adapter: Any, name: Optional[str] = None) -> bool:
        """
        Подключить адаптер к менеджеру.

        Адаптер предоставляет дополнительную функциональность (интеграция
        с процессом, упрощённый API и т.д.).

        Args:
            adapter: Экземпляр адаптера (наследник BaseAdapter)
            name:    Имя адаптера. Рекомендуется указывать явно.
                     Если не указано — определяется из имени класса.

        Returns:
            True если адаптер успешно подключён

        Example:
            >>> manager.attach_adapter(CommandAdapter(manager, process), name="command")
            >>> adapter = manager.get_adapter("command")
        """
        if adapter is None:
            return False

        if name is None:
            name = get_adapter_name_from_class(adapter.__class__.__name__)

        self._adapters[name] = adapter

        if hasattr(adapter, 'manager'):
            adapter.manager = self

        return True

    def get_adapter(self, name: Optional[str] = None) -> Optional[Any]:
        """
        Получить адаптер по имени (РЕКОМЕНДУЕМЫЙ способ доступа).

        Args:
            name: Имя адаптера. Если не указано — возвращается первый адаптер.

        Returns:
            Адаптер или None если не найден
        """
        if name is None:
            for adapter in self._adapters.values():
                if adapter is not None:
                    return adapter
            return None

        return self._adapters.get(name) or None

    def has_adapter(self, name: str) -> bool:
        """Проверить наличие адаптера по имени."""
        return name in self._adapters

    def list_adapters(self) -> List[str]:
        """Список имён подключённых адаптеров."""
        return list(self._adapters.keys())

    def detach_adapter(self, name: str) -> bool:
        """
        Отключить адаптер от менеджера.

        Args:
            name: Имя адаптера

        Returns:
            True если адаптер был подключён и отключён, False если не найден
        """
        if name in self._adapters:
            del self._adapters[name]
            return True
        return False

    # =========================================================================
    # ПУБЛИЧНЫЙ API — СТАТИСТИКА
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """
        Статистика менеджера: имя, статус, список адаптеров.

        Returns:
            dict с ключами: manager_name, is_initialized, process_name, adapters
        """
        stats: Dict[str, Any] = {
            "manager_name": self.manager_name,
            "is_initialized": self.is_initialized,
            "process_name": (
                getattr(self.process, 'name', 'unknown') if self.process else 'standalone'
            ),
            "adapters": list(self._adapters.keys()),
        }

        if self._adapters:
            adapters_info: Dict[str, Any] = {}
            for adapter_name, adapter in self._adapters.items():
                if adapter is None:
                    adapters_info[adapter_name] = {}
                elif hasattr(adapter, 'get_stats'):
                    try:
                        adapters_info[adapter_name] = adapter.get_stats()
                    except Exception:
                        adapters_info[adapter_name] = {}
                else:
                    adapters_info[adapter_name] = {}
            stats["adapters_info"] = adapters_info

        return stats

    # =========================================================================
    # ПУБЛИЧНЫЙ API — ДИАГНОСТИКА
    # =========================================================================

    def get_debug_info(self) -> Dict[str, Any]:
        """
        Подробная информация для отладки.

        Returns:
            dict с ключами: manager_name, is_initialized, process_name,
            adapters, adapter_details, available_methods,
            observable_managers (если ObservableMixin подключён)
        """
        info: Dict[str, Any] = {
            'manager_name': self.manager_name,
            'is_initialized': self.is_initialized,
            'process_name': (
                getattr(self.process, 'name', 'unknown') if self.process else 'standalone'
            ),
            'adapters': list(self._adapters.keys()),
            'adapter_details': {
                n: type(a).__name__ if a is not None else None
                for n, a in self._adapters.items()
            },
            'available_methods': [
                m for m in dir(self)
                if not m.startswith('__') and callable(getattr(self, m, None))
            ],
        }

        if hasattr(self, 'get_available_methods'):
            try:
                obs = self.get_available_methods()
                info['observable_managers'] = obs.get('managers', [])
                info['observable_methods'] = {
                    'private': len(obs.get('private', [])),
                    'public': len(obs.get('public', [])),
                }
            except Exception:
                pass

        return info

    def print_debug_info(self) -> None:
        """Вывести диагностическую информацию через логгер."""
        import json
        info = self.get_debug_info()
        self._log_debug(
            f"Debug Info: {self.__class__.__name__}\n{json.dumps(info, indent=2, ensure_ascii=False)}"
        )

    def __str__(self) -> str:
        return f"{self.__class__.__name__}(name={self.manager_name!r}, initialized={self.is_initialized})"

    def __repr__(self) -> str:
        return self.__str__()
