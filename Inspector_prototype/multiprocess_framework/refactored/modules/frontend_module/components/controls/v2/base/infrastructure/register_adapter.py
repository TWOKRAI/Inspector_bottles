# -*- coding: utf-8 -*-
"""
Адаптер к IRegistersManager — инкапсулирует чтение/запись/подписку.

Универсальный мост для любых контролов, привязанных к регистру.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from frontend_module.schemas.register_binding import (
    RegisterFieldMeta,
    ResolvedMeta,
)


def _extract_value(reg: Any, field_name: str) -> Any:
    """Извлечь значение поля из регистра."""
    val = getattr(reg, field_name, None)
    return getattr(val, "value", val) if val is not None else val


def _ensure_list(arr: Any, min_len: int = 0) -> list:
    """Нормализовать значение в list для чтения/записи по индексу."""
    if arr is None:
        return [0] * max(1, min_len)
    if isinstance(arr, (list, tuple)):
        lst = list(arr)
        while len(lst) < min_len:
            lst.append(0)
        return lst
    return [arr]


class RegisterAdapter:
    """
    Инкапсулирует общение с RegistersManager (IRegistersManager).
    Для subscribe с index хранит wrapped callback для корректной отписки.
    """

    def __init__(self, registers_manager: Any) -> None:
        self._rm = registers_manager
        self._subscriptions: dict[tuple, Callable[[Any], None]] = {}

    def get_field_metadata(self, register_name: str, field_name: str) -> Optional[dict]:
        """Сырые метаданные поля."""
        if not self._rm:
            return None
        return self._rm.get_field_metadata(register_name, field_name)

    def resolve_meta(
        self,
        register_name: str,
        field_name: str,
        config: Any,
    ) -> Optional[ResolvedMeta]:
        """ResolvedMeta = слияние метаданных регистра + config."""
        meta_dict = self.get_field_metadata(register_name, field_name)
        if not meta_dict and not register_name:
            return None
        meta = RegisterFieldMeta.from_dict(meta_dict or {})
        return ResolvedMeta.merge(meta, config or {}, field_name)

    def read(
        self,
        register_name: str,
        field_name: str,
        index: Optional[int] = None,
    ) -> Any:
        """Текущее значение поля. При index — элемент списка."""
        if not self._rm:
            return None
        reg = self._rm.get_register(register_name)
        if not reg:
            return None
        raw = _extract_value(reg, field_name)
        if index is not None:
            lst = _ensure_list(raw, index + 1)
            return lst[index] if index < len(lst) else 0
        return raw

    def write(
        self,
        register_name: str,
        field_name: str,
        value: Any,
        index: Optional[int] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        Записать значение. При index — обновить элемент списка.
        """
        if not self._rm:
            return False, "RegistersManager отсутствует"
        if index is not None:
            reg = self._rm.get_register(register_name)
            if not reg:
                return False, "Регистр не найден"
            raw = _extract_value(reg, field_name)
            lst = _ensure_list(raw, index + 1)
            if index >= len(lst):
                lst.extend([0] * (index - len(lst) + 1))
            lst[index] = value
            value = lst
        if hasattr(self._rm, "set_field_value"):
            return self._rm.set_field_value(register_name, field_name, value)
        reg = self._rm.get_register(register_name)
        if not reg:
            return False, "Регистр не найден"
        setattr(reg, field_name, value)
        return True, None

    def subscribe(
        self,
        register_name: str,
        field_name: str,
        callback: Callable[[Any], None],
        index: Optional[int] = None,
    ) -> None:
        """Подписаться на изменение поля. При index — callback получает элемент."""
        if not self._rm or not hasattr(self._rm, "subscribe"):
            return

        key = (register_name, field_name, id(callback))

        if index is not None:

            def _wrapped(full: Any) -> None:
                lst = _ensure_list(full, index + 1)
                callback(lst[index] if index < len(lst) else 0)

            self._subscriptions[key] = _wrapped
            self._rm.subscribe(register_name, field_name, _wrapped)
        else:
            self._subscriptions[key] = callback
            self._rm.subscribe(register_name, field_name, callback)

    def unsubscribe(
        self,
        register_name: str,
        field_name: str,
        callback: Callable[[Any], None],
        index: Optional[int] = None,
    ) -> None:
        """Отписаться от поля."""
        key = (register_name, field_name, id(callback))
        to_unsub = self._subscriptions.pop(key, None)
        if to_unsub and self._rm and hasattr(self._rm, "unsubscribe"):
            self._rm.unsubscribe(register_name, field_name, to_unsub)
