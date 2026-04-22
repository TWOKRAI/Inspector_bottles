# -*- coding: utf-8 -*-
"""
Обобщённый менеджер регистров.

Композиция ``RegistersContainer`` (data_schema_module): хранение, метаданные, dump/validate.
Уникально здесь: pub/sub, ``set_field_value`` + dispatch, ``send_callback``.

См. ``registers_module/DECISIONS.md`` (ADR-RM-001).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple

from data_schema_module import RegistersContainer

from .dispatch import resolve_dispatch_targets

logger = logging.getLogger(__name__)


class RegistersManager:
    """
    Менеджер регистров: ``{имя: экземпляр модели}``. Типы моделей определяет приложение;
    сериализация и метаданные — через ``RegistersContainer`` / ``SchemaMixin``.

    connection_map: опциональный override — register_name -> имя процесса для register_update
        (если нет process_targets в routing поля и нет register_dispatch на классе).
    send_callback: вызывается при изменении регистра, если есть хотя бы одна цель доставки.
    """

    def __init__(
        self,
        registers: Optional[Dict[str, Any]] = None,
        connection_map: Optional[Dict[str, str]] = None,
        send_callback: Optional[Callable[[str, str, str, Any, Dict[str, Any]], None]] = None,
    ):
        """
        Args:
            registers: Словарь {имя_регистра: экземпляр_модели}. Если None — пустой менеджер.
            connection_map: {register_name: process_name} — fallback для send_callback (см. ROUTING_GLOSSARY.md).
            send_callback: (channel, register_name, field_name, value, snapshot) — вызов при изменении.
        """
        self._container = RegistersContainer(registers or {})
        self._connection_map: Dict[str, str] = dict(connection_map) if connection_map else {}
        self._send_callback: Optional[Callable[[str, str, str, Any, Dict[str, Any]], None]] = send_callback
        self._global_observers: List[Callable[[str, str, Any], None]] = []
        self._field_observers: Dict[Tuple[str, str], List[Callable[[Any], None]]] = defaultdict(list)

    def get_register(self, name: str) -> Optional[Any]:
        """Получить экземпляр регистра по имени."""
        return self._container.get_register(name)

    def set_connection(self, register_name: str, backend_channel: str) -> None:
        """Привязать регистр к бэкенд-каналу (connection)."""
        self._connection_map[register_name] = backend_channel

    def set_send_callback(self, callback: Optional[Callable[[str, str, str, Any, Dict[str, Any]], None]]) -> None:
        """Установить callback для отправки изменений в бэкенд."""
        self._send_callback = callback

    def subscribe(
        self,
        register_name: str,
        field_name: str,
        callback: Callable[[Any], None],
    ) -> None:
        """Подписать callback(value) на изменение поля."""
        key = (register_name, field_name)
        if callback not in self._field_observers[key]:
            self._field_observers[key].append(callback)

    def unsubscribe(
        self,
        register_name: str,
        field_name: str,
        callback: Callable[[Any], None],
    ) -> None:
        """Отписать callback от поля."""
        key = (register_name, field_name)
        try:
            self._field_observers[key].remove(callback)
        except ValueError:
            pass

    def subscribe_all(
        self,
        callback: Callable[[str, str, Any], None],
    ) -> None:
        """Подписать callback(register_name, field_name, value) на любое изменение."""
        if callback not in self._global_observers:
            self._global_observers.append(callback)

    def unsubscribe_all(self, callback: Callable[[str, str, Any], None]) -> None:
        """Отписать глобальный observer."""
        try:
            self._global_observers.remove(callback)
        except ValueError:
            pass

    def set_field_value(
        self,
        register_name: str,
        field_name: str,
        value: Any,
    ) -> Tuple[bool, Optional[str]]:
        """Установить значение поля и уведомить подписчиков. При connection — вызвать send_callback."""
        reg = self.get_register(register_name)
        if reg is None:
            return False, f"Регистр '{register_name}' не найден"
        if not hasattr(reg, field_name):
            return False, f"Поле '{field_name}' не найдено в регистре '{register_name}'"
        is_valid, err = self.validate_field_value(register_name, field_name, value)
        if not is_valid:
            return False, err
        try:
            setattr(reg, field_name, value)
        except Exception as exc:
            return False, str(exc)
        logger.debug(
            "set_field_value: %s.%s = %r",
            register_name,
            field_name,
            value,
        )
        self._notify_observers(register_name, field_name, value)
        if self._send_callback:
            targets = resolve_dispatch_targets(
                register_name,
                field_name,
                reg,
                self._connection_map,
                self._get_field_metadata_for_dispatch,
            )
            if targets:
                snapshot = (
                    reg.model_dump(mode="json")
                    if hasattr(reg, "model_dump")
                    else {}
                )
                for channel in targets:
                    full_channel = (
                        f"control_{channel}" if not channel.startswith("control_") else channel
                    )
                    try:
                        self._send_callback(
                            full_channel, register_name, field_name, value, snapshot
                        )
                    except Exception as e:
                        logger.error(
                            "send_callback failed for %s.%s → %s: %s",
                            register_name,
                            field_name,
                            full_channel,
                            e,
                            exc_info=True,
                        )
        return True, None

    def _get_field_metadata_for_dispatch(self, register_name: str, field_name: str) -> Dict[str, Any]:
        return self.get_field_metadata(register_name, field_name)

    def notify_field_changed(
        self,
        register_name: str,
        field_name: str,
        value: Any,
    ) -> None:
        """Уведомить только field-подписчиков (без глобальных и send_callback)."""
        for cb in list(self._field_observers.get((register_name, field_name), [])):
            try:
                cb(value)
            except Exception as e:
                logger.warning(
                    "notify_field_changed observer failed for %s.%s: %s",
                    register_name,
                    field_name,
                    e,
                    exc_info=True,
                )

    def _notify_observers(self, register_name: str, field_name: str, value: Any) -> None:
        """Уведомить field- и global-подписчиков."""
        for cb in list(self._field_observers.get((register_name, field_name), [])):
            try:
                cb(value)
            except Exception as e:
                logger.warning(
                    "field observer failed for %s.%s: %s",
                    register_name,
                    field_name,
                    e,
                    exc_info=True,
                )
        for cb in list(self._global_observers):
            try:
                cb(register_name, field_name, value)
            except Exception as e:
                logger.warning(
                    "global observer failed for %s.%s: %s",
                    register_name,
                    field_name,
                    e,
                    exc_info=True,
                )

    def register_names(self) -> List[str]:
        """Список имён зарегистрированных регистров."""
        return self._container.register_names()

    def set_register(self, name: str, instance: Any) -> None:
        """Установить экземпляр регистра (для динамического добавления/замены)."""
        self._container[name] = instance

    def get_field_metadata(
        self,
        register_name: str,
        field_name: str,
        language: Optional[str] = None,
        lang: Optional[str] = None,
        translation_manager: Any = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Метаданные поля через SchemaMixin (кэш FieldMeta)."""
        effective_lang = lang if lang is not None else language
        return self._container.get_field_metadata(
            register_name,
            field_name,
            effective_lang,
            translation_manager,
        )

    def validate_field_value(
        self,
        register_name: str,
        field_name: str,
        value: Any,
        current_access_level: int = 0,
    ) -> Tuple[bool, Optional[str]]:
        """Проверка через RegistersContainer → SchemaMixin.validate_field (если регистр — SchemaMixin)."""
        if self._container.get_register(register_name) is None:
            return False, f"Регистр '{register_name}' не найден"
        return self._container.validate_field(
            register_name,
            field_name,
            value,
            access_level=current_access_level,
        )

    def model_dump_all(self) -> Dict[str, Any]:
        """Экспорт всех регистров в словарь."""
        return self._container.model_dump_all()

    def model_validate_all(self, data: Dict[str, Any], strict: bool = False) -> None:
        """Загрузить данные в регистры (in-place в контейнере)."""
        self._container.model_validate_all(data, strict=strict)
