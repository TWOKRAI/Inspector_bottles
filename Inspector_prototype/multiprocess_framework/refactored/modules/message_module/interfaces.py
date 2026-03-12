# -*- coding: utf-8 -*-
"""
Публичные контракты message_module.

IMessage        — контракт любого сообщения в системе.
IMessageFactory — фабрика для создания сообщений.

Правило: внешние модули импортируют только из interfaces.py, не из core/.
Создавать сообщения через MessageFactory.create() или Message.create().

Правило Dict at Boundary (ADR-008):
    При передаче через границу процессов:  msg.to_dict()
    При получении из очереди:              Message.from_dict(raw_dict)
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Set, Union


class IMessage(ABC):
    """Контракт универсального сообщения межпроцессного взаимодействия.

    Единый «язык» общения между менеджерами и процессами.
    Транспортируется через RouterManager/каналы в виде dict,
    но внутри процесса используется как объект Message.

    Жизненный цикл сообщения:
        1. Создание:  Message.create(MessageType.COMMAND, sender="proc_1", ...)
                      или через MessageAdapter (рекомендуется в процессах)
        2. Отправка:  router.send(msg)           # объект → to_dict() внутри
        3. Передача:  queue.put(msg.to_dict())   # на границе процессов — dict
        4. Получение: Message.from_dict(raw)     # восстановление из dict
        5. Обработка: handler(msg)               # работа с объектом

    Типы сообщений (MessageType):
        GENERAL   — произвольное содержимое
        COMMAND   — команда для выполнения действия
        LOG       — запись в централизованный лог
        SYSTEM    — управление жизненным циклом процессов
        BROADCAST — широковещательная рассылка
        DATA      — передача больших данных (опционально shared memory)
        REQUEST   — запрос с ожиданием ответа
        RESPONSE  — ответ на REQUEST
        EVENT     — событие в стиле pub/sub
    """

    # =========================================================================
    # Обязательные атрибуты (ожидаются в любом сообщении)
    # =========================================================================

    @property
    @abstractmethod
    def id(self) -> str:
        """Уникальный идентификатор сообщения (генерируется автоматически)."""

    @property
    @abstractmethod
    def type(self) -> str:
        """Тип сообщения — значение из MessageType (например, 'command')."""

    @property
    @abstractmethod
    def sender(self) -> str:
        """Имя модуля/процесса-отправителя."""

    @property
    @abstractmethod
    def targets(self) -> List[str]:
        """Список имён получателей (например, ['process_2', 'logger'])."""

    @property
    @abstractmethod
    def timestamp(self) -> float:
        """Unix-timestamp создания сообщения."""

    @property
    @abstractmethod
    def priority(self) -> str:
        """Приоритет: 'urgent' | 'high' | 'normal' | 'low'."""

    @property
    @abstractmethod
    def channel(self) -> Optional[str]:
        """Имя канала доставки или None (определяется dispatcher'ом роутера)."""

    # =========================================================================
    # Fluent API (цепочки вызовов для наполнения сообщения)
    # =========================================================================

    @abstractmethod
    def set_priority(self, priority: Union[str, Any]) -> "IMessage":
        """Установить приоритет. Возвращает self для chaining.

        priority: Priority enum или строка 'urgent'|'high'|'normal'|'low'
        """

    @abstractmethod
    def set_targets(self, targets: List[str]) -> "IMessage":
        """Установить список получателей. Возвращает self."""

    @abstractmethod
    def add_target(self, target: str) -> "IMessage":
        """Добавить получателя (без дублей). Возвращает self."""

    @abstractmethod
    def set_channel(self, channel: str) -> "IMessage":
        """Установить канал доставки. Возвращает self."""

    @abstractmethod
    def add_metadata(self, key: str, value: Any) -> "IMessage":
        """Добавить пару ключ/значение в metadata. Возвращает self."""

    # =========================================================================
    # Валидация
    # =========================================================================

    @abstractmethod
    def validate(self) -> bool:
        """Проверить сообщение перед отправкой.

        Returns:
            True если валидно.

        Raises:
            MessageValidationError: При нарушении структуры или пустых
                обязательных полях.
        """

    @abstractmethod
    def is_valid(self) -> bool:
        """Проверить валидность без выброса исключения.

        Returns:
            True если валидно, False иначе.
        """

    # =========================================================================
    # Сериализация (Dict at Boundary)
    # =========================================================================

    @abstractmethod
    def to_dict(
        self,
        exclude_none: bool = True,
        exclude_fields: Optional[Set[str]] = None,
        include_fields: Optional[Set[str]] = None,
    ) -> Dict[str, Any]:
        """Сериализовать в dict.

        Используется при передаче через границу процессов (ADR-008).

        Args:
            exclude_none:   Не включать поля со значением None (по умолчанию True).
            exclude_fields: Множество имён полей для исключения.
            include_fields: Если задано — включить только эти поля.

        Returns:
            Словарь с данными сообщения без приватных полей (_*).
        """

    @abstractmethod
    def to_json(
        self,
        exclude_none: bool = True,
        indent: Optional[int] = None,
    ) -> str:
        """Сериализовать в JSON-строку."""

    # =========================================================================
    # Словарный доступ (удобство работы с полями)
    # =========================================================================

    @abstractmethod
    def get(self, key: str, default: Any = None) -> Any:
        """Безопасно получить поле сообщения (None → default)."""

    @abstractmethod
    def clone(self) -> "IMessage":
        """Создать копию с новым id и текущим timestamp."""

    @abstractmethod
    def get_schema_info(self) -> Optional[Dict[str, str]]:
        """Вернуть информацию о Pydantic-схеме или None.

        Returns:
            {'schema_name': ..., 'schema_module': ..., 'schema_path': ...}
            или None если схема не использовалась.
        """


class IMessageFactory(ABC):
    """Контракт фабрики сообщений.

    Единственный способ создавать сообщения в коде менеджеров и процессов.
    Упрощает тестирование — фабрику можно подменить моком.

    Рекомендуется использовать MessageAdapter (обёртку над фабрикой)
    внутри процессов, а не вызывать фабрику напрямую.
    """

    @abstractmethod
    def create(
        self,
        msg_type: Union[str, Any],
        sender: str,
        **kwargs: Any,
    ) -> IMessage:
        """Создать сообщение по типу и отправителю.

        Args:
            msg_type: MessageType enum или строка ('command', 'log', ...)
            sender:   Имя отправителя.
            **kwargs: Поля сообщения (targets, command, level, ...).

        Returns:
            Экземпляр Message.
        """

    @abstractmethod
    def from_dict(self, data: Dict[str, Any]) -> IMessage:
        """Восстановить сообщение из словаря (после границы процесса)."""

    @abstractmethod
    def from_json(self, json_str: str) -> IMessage:
        """Восстановить сообщение из JSON-строки."""
