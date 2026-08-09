"""
Интерфейсы для DispatchModule.

Определяет контракты для компонентов модуля диспетчеризации сообщений.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Callable, Optional, List

from .types.types import DispatchStrategy
from ..observability_declarations import declare_log_source

#: Имя источника, которым модуль штампует свои записи (Ф2.6, решение Р-2.6-В).
#: Четырнадцать литералов ``"dispatcher"`` внутри ``core/dispatcher.py`` заменены
#: ссылкой сюда — см. пояснение в ``command_module/interfaces.py``.
#:
#: **Значение — точечное имя пакета, а не короткий ярлык** (Р-2.6-Д, правка после
#: ревью решений). Плоское имя — лист без поддерева: правило по префиксу на нём не
#: работает, и каждый новый файл модуля пришлось бы заводить в конфиге руками.
#: Точечное имя даёт обратное — правило ``multiprocess_framework.modules`` действует
#: на всё поддерево, а новый файл наследует его без единой правки. Так же выводят имя
#: логгера stdlib (``getLogger(__name__)``), logback (FQCN), .NET (``ILogger<T>``) и
#: OTel (``InstrumentationScope.name``); короткие ручки в индустрии существуют, но как
#: алиас КОНФИГА (Spring ``logging.group``) — у нас это задача 2.5, а не личность записи.
#:
#: В файл имя пишется сокращённым (``LoggerChannelSchema.name_max_len``): без этого
#: переход дал бы +4.7…16.4% к весу логов — замер там же.
LOG_SOURCE = declare_log_source(
    "multiprocess_framework.modules.dispatch_module",
    owner=__name__,
)
"""Ф2.7: объявление активное — имя попадает в каталог источников процесса
(``declared_sources``), то есть видно ДО первой записи. Два модуля с одним
именем — отказ на импорте, а не молчаливый выбор по порядку импортов."""


class IDispatcher(ABC):
    """
    Интерфейс для диспетчера сообщений.

    Определяет контракт для всех реализаций диспетчера.
    """

    @property
    @abstractmethod
    def manager_name(self) -> str:
        """Уникальное имя менеджера (как у BaseManager)."""
        pass

    @abstractmethod
    def register_handler(
        self,
        key: str,
        handler: Callable,
        expects_full_message: bool = False,
        metadata: Dict[str, Any] = None,
        efficiency: int = 0,
        tags: List[str] = None,
        strategy: Optional[DispatchStrategy] = None,
    ) -> bool:
        """
        Зарегистрировать обработчик.

        Args:
            key: Уникальный ключ обработчика
            handler: Функция-обработчик
            expects_full_message: Если True, обработчик получает всё сообщение
            metadata: Дополнительные метаданные
            efficiency: Уровень эффективности обработчика
            tags: Список тегов для группировки
            strategy: Стратегия для регистрации

        Returns:
            True если регистрация успешна
        """
        pass

    @abstractmethod
    def dispatch(self, message: Dict[str, Any], key_field: str = "command", data_field: str = "data") -> Any:
        """
        Диспетчеризовать сообщение.

        Args:
            message: Сообщение для обработки
            key_field: Поле в сообщении, содержащее ключ диспетчеризации
            data_field: Поле в сообщении, содержащее данные для обработки

        Returns:
            Результат работы обработчика или словарь с ошибкой
        """
        pass

    @abstractmethod
    def get_handler_info(self, key: str) -> Optional[Dict]:
        """
        Получить информацию о обработчике.

        Args:
            key: Ключ обработчика

        Returns:
            Словарь с информацией или None
        """
        pass

    @abstractmethod
    def get_all_handlers(self) -> List[Dict]:
        """
        Получить информацию обо всех обработчиках.

        Returns:
            Список словарей с информацией об обработчиках
        """
        pass

    @abstractmethod
    def get_handlers_by_tag(self, tag: str) -> List[Dict]:
        """
        Получить обработчики по тегу.

        Args:
            tag: Тег для поиска

        Returns:
            Список словарей с информацией об обработчиках
        """
        pass


# Публичный контракт модуля (Ф8 H.1 / NEW-10): перечислен явно, чтобы
# случайный top-level импорт не становился частью API.
__all__ = [
    "DispatchStrategy",
    "IDispatcher",
]
