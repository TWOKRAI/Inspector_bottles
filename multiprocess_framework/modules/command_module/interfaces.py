"""
Интерфейсы для CommandModule.

Определяют контракты для командных менеджеров и адаптеров.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Callable, List, Optional

from ..base_manager.interfaces import IBaseManager
from ..observability_declarations import declare_log_source

#: Имя источника, которым модуль штампует свои записи (Ф2.6, решение Р-2.6-В).
#:
#: Объявлено ЗДЕСЬ, рядом с публичным контрактом, а не литералом на call-site.
#: До Ф2.6 строка ``"command_manager"`` была напечатана дважды: в шести штампах
#: внутри ``command_manager.py`` и ещё раз — в правиле маршрутизации. Расхождение
#: между копиями и есть «правило написано неправильно», а обнаружить его было
#: нечем: непойманное правило ничего не теряет, значит счётчику потерь расти не с
#: чего. Пока обе стороны берут строку отсюда, расходиться нечему.
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
    "multiprocess_framework.modules.command_module",
    owner=__name__,
)
"""Ф2.7: объявление активное — имя попадает в каталог источников процесса
(``declared_sources``), то есть видно ДО первой записи. Два модуля с одним
именем — отказ на импорте, а не молчаливый выбор по порядку импортов."""


class ICommandManager(IBaseManager, ABC):
    """
    Интерфейс для командных менеджеров.

    Определяет контракт для регистрации и выполнения команд.
    """

    @abstractmethod
    def register_command(
        self,
        command_name: str,
        handler: Callable,
        expects_full_message: bool = False,
        metadata: Dict[str, Any] = None,
        efficiency: int = 0,
        tags: List[str] = None,
        strategy: Optional[Any] = None,
        **kwargs,
    ) -> bool:
        """
        Регистрация новой команды.

        Args:
            command_name: Название команды
            handler: Функция-обработчик команды
            expects_full_message: Если True, обработчик получает всё сообщение
            metadata: Дополнительные метаданные команды
            efficiency: Уровень эффективности
            tags: Список тегов для группировки
            strategy: Стратегия для регистрации
            **kwargs: Дополнительные аргументы

        Returns:
            bool: Успешность регистрации
        """
        pass

    @abstractmethod
    def handle_command(self, message: Dict) -> Any:
        """
        Обработка командного сообщения.

        Args:
            message: Сообщение для обработки

        Returns:
            Результат выполнения команды или сообщение об ошибке
        """
        pass

    @abstractmethod
    def get_commands(self) -> List[Dict]:
        """
        Получение списка всех зарегистрированных команд.

        Returns:
            Список словарей с информацией о командах
        """
        pass

    @abstractmethod
    def get_command_info(self, command_name: str) -> Optional[Dict]:
        """
        Получение информации о конкретной команде.

        Args:
            command_name: Название команды

        Returns:
            Словарь с информацией о команде или None
        """
        pass

    @abstractmethod
    def get_commands_by_tag(self, tag: str) -> List[Dict]:
        """
        Получение команд по тегу.

        Args:
            tag: Тег для фильтрации

        Returns:
            Список команд с указанным тегом
        """
        pass

    @abstractmethod
    def update_command_metadata(self, command_name: str, metadata: Dict[str, Any]) -> bool:
        """
        Обновление метаданных команды.

        Args:
            command_name: Название команды
            metadata: Новые метаданные

        Returns:
            True если обновлено, False в случае ошибки
        """
        pass

    @abstractmethod
    def update_command_tags(self, command_name: str, tags: List[str]) -> bool:
        """
        Обновление тегов команды.

        Args:
            command_name: Название команды
            tags: Новые теги

        Returns:
            True если обновлено, False в случае ошибки
        """
        pass

    @abstractmethod
    def overwrite_command(
        self,
        command_name: str,
        handler: Callable,
        expects_full_message: bool = False,
        metadata: Dict[str, Any] = None,
        efficiency: int = 0,
        tags: List[str] = None,
    ) -> bool:
        """
        Принудительная перезапись команды.

        Args:
            command_name: Название команды
            handler: Новый обработчик
            expects_full_message: Если True, обработчик получает всё сообщение
            metadata: Метаданные команды
            efficiency: Уровень эффективности
            tags: Список тегов

        Returns:
            True если перезаписано, False в случае ошибки
        """
        pass


# Публичный контракт модуля (Ф8 H.1 / NEW-10): перечислен явно, чтобы
# случайный top-level импорт не становился частью API.
__all__ = [
    "ICommandManager",
]
