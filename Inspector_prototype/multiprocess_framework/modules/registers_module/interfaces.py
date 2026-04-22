# -*- coding: utf-8 -*-
"""
Интерфейсы модуля регистров.

Полный runtime-контракт ``RegistersManager`` для подстановки в тестах, роутинг и UI
(``build_routing_map``, ``FrontendRegistersBridge``). См. ADR-RM-001, ADR-RM-005.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple


class IRegistersManager(Protocol):
    """
    Протокол менеджера регистров: хранение, pub/sub, запись с dispatch.
    """

    # --- Storage (делегирование в контейнер / экземпляры) ---
    def get_register(self, name: str) -> Optional[Any]:
        """Получить экземпляр регистра по имени."""
        ...

    def set_register(self, name: str, instance: Any) -> None:
        """Добавить или заменить экземпляр регистра по имени."""
        ...

    def register_names(self) -> List[str]:
        """Список имён зарегистрированных регистров."""
        ...

    def get_field_metadata(self, register_name: str, field_name: str, **kwargs: Any) -> Dict[str, Any]:
        """Метаданные поля (min, max, unit, routing, access_level и т.д.)."""
        ...

    def validate_field_value(
        self,
        register_name: str,
        field_name: str,
        value: Any,
        current_access_level: int = 0,
    ) -> Tuple[bool, Optional[str]]:
        """Валидация значения поля. Возвращает (is_valid, error_message)."""
        ...

    def model_dump_all(self) -> Dict[str, Any]:
        """Сериализация всех регистров в словарь."""
        ...

    def model_validate_all(self, data: Dict[str, Any], strict: bool = False) -> None:
        """Загрузка данных в регистры (in-place)."""
        ...

    # --- Pub/Sub ---
    def subscribe(self, register_name: str, field_name: str, callback: Callable[[Any], None]) -> None:
        """Подписка callback(value) на поле."""
        ...

    def unsubscribe(self, register_name: str, field_name: str, callback: Callable[[Any], None]) -> None:
        """Отписка от поля."""
        ...

    def subscribe_all(self, callback: Callable[[str, str, Any], None]) -> None:
        """Глобальная подписка callback(register_name, field_name, value)."""
        ...

    def unsubscribe_all(self, callback: Callable[[str, str, Any], None]) -> None:
        """Отписка глобального observer."""
        ...

    # --- Запись и dispatch ---
    def set_field_value(
        self,
        register_name: str,
        field_name: str,
        value: Any,
    ) -> Tuple[bool, Optional[str]]:
        """Установить значение, уведомить подписчиков, при необходимости send_callback."""
        ...

    def notify_field_changed(self, register_name: str, field_name: str, value: Any) -> None:
        """Уведомить только подписчиков поля (без глобальных и send_callback)."""
        ...

    # --- Конфигурация доставки ---
    def set_connection(self, register_name: str, backend_channel: str) -> None:
        """Привязать регистр к процессу/каналу (connection_map)."""
        ...

    def set_send_callback(
        self,
        callback: Optional[Callable[[str, str, str, Any, Dict[str, Any]], None]],
    ) -> None:
        """
        Callback при изменении с целью доставки:
        ``(channel, register_name, field_name, value, snapshot)``.
        ``None`` отключает отправку.
        """
        ...
