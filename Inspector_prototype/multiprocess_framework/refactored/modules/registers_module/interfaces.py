# -*- coding: utf-8 -*-
"""
Интерфейсы модуля регистров.

Минимальный контракт для независимого тестирования и подстановки реализаций (SOLID).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, Tuple


class IRegistersManager(Protocol):
    """
    Протокол менеджера регистров.
    Любая реализация с этими методами совместима с роутером и конвертером.
    """

    def get_register(self, name: str) -> Optional[Any]:
        """Получить экземпляр регистра по имени."""
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
        """Экспорт всех регистров в словарь."""
        ...

    def model_validate_all(self, data: Dict[str, Any], strict: bool = False) -> None:
        """Загрузка всех регистров из словаря."""
        ...

    def register_names(self) -> List[str]:
        """Список имён зарегистрированных регистров."""
        ...


class IRegistersConverter(Protocol):
    """
    Протокол конвертера регистров.
    Работа с dict, json, yaml, flat-форматом.
    """

    def to_dict(self, registers: IRegistersManager) -> Dict[str, Any]:
        """Экспорт в словарь."""
        ...

    def from_dict(self, data: Dict[str, Any], registers: IRegistersManager) -> None:
        """Импорт из словаря в существующий менеджер."""
        ...

    def to_flat_dict(self, registers: IRegistersManager, prefix: str = "") -> Dict[str, Any]:
        """Экспорт в плоский словарь (для рецептов)."""
        ...

    def from_flat_dict(self, flat_dict: Dict[str, Any], registers: IRegistersManager, prefix: str = "") -> None:
        """Импорт из плоского словаря."""
        ...
