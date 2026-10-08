# -*- coding: utf-8 -*-
"""
Публичные контракты message_module.

IMessage — контракт любого сообщения (Protocol, structural typing).

Правило: внешние модули импортируют только из interfaces.py, не из core/.
Создавать сообщения через Message.create() или MessageAdapter.

Правило Dict at Boundary (ADR-008):
    При передаче через границу процессов:  msg.to_dict()
    При получении из очереди:              Message.from_dict(raw_dict)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Union

try:
    from typing import Protocol, runtime_checkable
except ImportError:
    from typing_extensions import Protocol, runtime_checkable  # type: ignore[misc]


@runtime_checkable
class IMessage(Protocol):
    """Контракт сообщения (structural typing)."""

    id: str
    type: str
    sender: str
    targets: List[str]
    timestamp: float
    priority: str
    channel: Optional[str]

    def set_priority(self, priority: Union[str, Any]) -> "IMessage":
        """Установить приоритет (строка или enum ``Priority`` — берётся его ``.value``); вернуть self."""
        ...

    def set_targets(self, targets: List[str]) -> "IMessage":
        """Заменить список получателей переданным списком (без копирования); вернуть self."""
        ...

    def add_target(self, target: str) -> "IMessage":
        """Добавить получателя, если его ещё нет в ``targets`` (дубликат пропускается); вернуть self."""
        ...

    def set_channel(self, channel: str) -> "IMessage":
        """Установить канал доставки (``channel``); вернуть self."""
        ...

    def add_metadata(self, key: str, value: Any) -> "IMessage":
        """Записать ``metadata[key] = value`` (существующий ключ перезаписывается); вернуть self."""
        ...

    def validate(self) -> bool:
        """Проверить сообщение; при успехе вернуть ``True``.

        Raises:
            MessageValidationError: пустой ``sender`` или ``targets``, неизвестный ``type``,
                пустое обязательное поле типа либо не прошла внешняя Pydantic-схема
                (если сообщение создано со схемой — проверяется только она)."""
        ...

    def is_valid(self) -> bool:
        """Как :meth:`validate`, но без исключения: ``True`` / ``False`` (``MessageValidationError`` → ``False``)."""
        ...

    def to_dict(
        self,
        exclude_none: bool = True,
        exclude_fields: Optional[Set[str]] = None,
        include_fields: Optional[Set[str]] = None,
    ) -> Dict[str, Any]:
        """Плоский dict сообщения для передачи через границу процессов (Dict at Boundary, ADR-008).

        Args:
            exclude_none: отбросить поля со значением ``None``.
            exclude_fields: дополнительные имена полей, которые нужно убрать.
            include_fields: если задано — оставить только эти поля (применяется последним).

        Пустые ``list``/``dict`` отбрасываются всегда; дополнительно убираются поля из
        ``MESSAGE_TYPE_EXCLUDE_FIELDS[type]`` (сейчас карта пуста — для типов ничего не исключается).
        """
        ...

    def to_json(
        self,
        exclude_none: bool = True,
        exclude_fields: Optional[Set[str]] = None,
        include_fields: Optional[Set[str]] = None,
        indent: Optional[int] = None,
    ) -> str:
        """JSON-строка того же содержимого, что :meth:`to_dict` (``ensure_ascii=False``, кириллица не экранируется)."""
        ...

    def get(self, key: str, default: Any = None) -> Any:
        """Значение атрибута ``key`` сообщения или ``default``, если атрибута нет (аналог ``dict.get``)."""
        ...

    def clone(self) -> "IMessage":
        """Копия сообщения с новыми ``id`` и ``timestamp``; прочие поля (в т.ч. внешняя схема) сохраняются.

        Исключение: для пустых ``targets`` и ``channel=None`` у копии снова применяются дефолты типа."""
        ...

    def get_schema_info(self) -> Optional[Dict[str, str]]:
        """Метаданные внешней Pydantic-схемы (``schema_name``/``schema_module``/``schema_path``) либо ``None``,
        если сообщение создано без схемы."""
        ...


# Публичный контракт модуля (Ф8 H.1 / NEW-10): перечислен явно, чтобы
# случайный top-level импорт не становился частью API.
__all__ = [
    "IMessage",
]
