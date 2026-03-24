# -*- coding: utf-8 -*-
"""
FrontendRegistersBridge — обёртка над RegistersManager для связи frontend с backend.

Реализует IRegistersManager, делегируя в registers_module.RegistersManager.
Настраивает connection_map и send_callback для отправки изменений через router.

router: ProcessModule (напр. GuiProcess прототипа). Имеет send_message(target, msg),
который делегирует в ProcessCommunication → RouterManager.queue_registry.send_to_queue.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from frontend_module.interfaces import IRegistersManager


def _build_send_callback(router: Any, process_name: str) -> Callable[[str, str, str, Any, Dict[str, Any]], None]:
    """
    Создать send_callback для RegistersManager.

    При изменении поля с connection отправляет сообщение через router.
    Формат: control_{channel} с data_type="register_update".
    """
    def _send(channel: str, register_name: str, field_name: str, value: Any, snapshot: Dict[str, Any]) -> None:
        if not router or not hasattr(router, "send_message"):
            return
        msg = {
            "type": "data",
            "data_type": "register_update",
            "data": {
                "register_name": register_name,
                "field_name": field_name,
                "value": value,
                "snapshot": snapshot,
            },
        }
        target = channel.replace("control_", "") if channel.startswith("control_") else channel
        try:
            router.send_message(target, msg)
        except Exception:
            pass

    return _send


class FrontendRegistersBridge:
    """
    Мост между frontend и RegistersManager.

    - Реализует IRegistersManager (делегирует в _registers)
    - connection_map: {register_name: process_name} — fallback, если нет register_dispatch / process_targets в схеме
    - send_callback: при set_field_value → отправка через router
    - apply_connection_map: применить connection_map и send_callback к RegistersManager
    """

    def __init__(
        self,
        registers_manager: Any,
        router: Optional[Any] = None,
        process_name: str = "gui",
        connection_map: Optional[Dict[str, str]] = None,
        send_callback: Optional[Callable[[str, str, str, Any, Dict[str, Any]], None]] = None,
    ):
        """
        Args:
            registers_manager: RegistersManager из registers_module
            router: ProcessModule (send_message → RouterManager) или объект с send_message(target, msg)
            process_name: Имя процесса (для логов)
            connection_map: {register_name: channel} — при изменении отправлять в channel
            send_callback: Кастомный callback. Если None и router задан — создаётся автоматически.
        """
        self._registers = registers_manager
        self._router = router
        self._process_name = process_name
        self._connection_map = dict(connection_map) if connection_map else {}

        if send_callback is not None:
            self._send_callback = send_callback
        elif router is not None:
            self._send_callback = _build_send_callback(router, process_name)
        else:
            self._send_callback = None

        self._apply_to_registers()

    def _apply_to_registers(self) -> None:
        """Применить connection_map и send_callback к RegistersManager."""
        for reg_name, channel in self._connection_map.items():
            self._registers.set_connection(reg_name, channel)
        self._registers.set_send_callback(self._send_callback)

    def set_connection_map(self, connection_map: Dict[str, str]) -> None:
        """Обновить connection_map и применить к RegistersManager."""
        self._connection_map = dict(connection_map)
        self._apply_to_registers()

    def set_router(self, router: Any) -> None:
        """Обновить router и пересоздать send_callback."""
        self._router = router
        self._send_callback = _build_send_callback(router, self._process_name) if router else None
        self._apply_to_registers()

    # --- IRegistersManager (делегирование) ---

    def get_register(self, name: str) -> Optional[Any]:
        return self._registers.get_register(name)

    def get_field_metadata(
        self,
        register_name: str,
        field_name: str,
        language: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return self._registers.get_field_metadata(register_name, field_name, language=language, **kwargs)

    def validate_field_value(
        self,
        register_name: str,
        field_name: str,
        value: Any,
        current_access_level: int = 0,
    ) -> Tuple[bool, Optional[str]]:
        return self._registers.validate_field_value(
            register_name, field_name, value, current_access_level
        )

    def set_field_value(
        self,
        register_name: str,
        field_name: str,
        value: Any,
    ) -> Tuple[bool, Optional[str]]:
        return self._registers.set_field_value(register_name, field_name, value)

    def subscribe(
        self,
        register_name: str,
        field_name: str,
        callback: Callable[[Any], None],
    ) -> None:
        self._registers.subscribe(register_name, field_name, callback)

    def unsubscribe(
        self,
        register_name: str,
        field_name: str,
        callback: Callable[[Any], None],
    ) -> None:
        self._registers.unsubscribe(register_name, field_name, callback)

    def subscribe_all(self, callback: Callable[[str, str, Any], None]) -> None:
        self._registers.subscribe_all(callback)

    def unsubscribe_all(self, callback: Callable[[str, str, Any], None]) -> None:
        self._registers.unsubscribe_all(callback)

    def notify_field_changed(
        self,
        register_name: str,
        field_name: str,
        value: Any,
    ) -> None:
        """Уведомить виджеты об изменении (при получении данных с бэкенда)."""
        self._registers.notify_field_changed(register_name, field_name, value)

    def register_names(self) -> List[str]:
        return self._registers.register_names()

    def set_register(self, name: str, instance: Any) -> None:
        self._registers.set_register(name, instance)

    def model_dump_all(self) -> Dict[str, Any]:
        return self._registers.model_dump_all()

    def model_validate_all(self, data: Dict[str, Any], strict: bool = False) -> None:
        self._registers.model_validate_all(data, strict=strict)

    @property
    def registers_manager(self) -> Any:
        """Доступ к исходному RegistersManager."""
        return self._registers
