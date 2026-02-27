# -*- coding: utf-8 -*-
"""
Построение карты маршрутизации по регистрам и отправка сообщений по ней.
(register_name, field_name) -> {router?, channel} для расширения роутера.
Сообщение: команда + ключ (register/field) + значение; ошибки передаются в error_callback.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Tuple

from .interfaces import IRegistersManager

# Константы для ErrorManager (архитектурный контракт)
ROUTING_NOT_FOUND = "ROUTING_NOT_FOUND"
PROCESS_UNREACHABLE = "PROCESS_UNREACHABLE"
MESSAGE_LOST = "MESSAGE_LOST"


def build_routing_map(registers: IRegistersManager) -> Dict[Tuple[str, str], Dict[str, str]]:
    """
    Строит карту: (register_name, field_name) -> {router?, channel}.
    Используется главным процессом для передачи в RouterManager и выбора канала по сообщению.
    """
    result: Dict[Tuple[str, str], Dict[str, str]] = {}
    for reg_name in registers.register_names():
        reg = registers.get_register(reg_name)
        if reg is None:
            continue
        fields = getattr(reg, "model_fields", None)
        if not fields:
            continue
        for field_name in fields.keys():
            meta = registers.get_field_metadata(reg_name, field_name)
            routing = meta.get("routing")
            if isinstance(routing, dict) and routing:
                result[(reg_name, field_name)] = {k: str(v) for k, v in routing.items()}
    return result


def get_routing_for_message(
    registers: IRegistersManager,
    register_name: str,
    field_name: str,
) -> Dict[str, str]:
    """
    Получить routing для конкретного register/field (для роутера по сообщению).
    Возвращает пустой dict, если маршрут не найден.
    """
    meta = registers.get_field_metadata(register_name, field_name)
    routing = meta.get("routing")
    if isinstance(routing, dict):
        return {k: str(v) for k, v in routing.items()}
    return {}


def send_register_message(
    router: Any,
    routing_map: Dict[Tuple[str, str], Dict[str, str]],
    register_name: str,
    field_name: str,
    value: Any,
    command: str = "write",
    error_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Отправить сообщение по карте маршрутизации: команда + register + field + значение.
    Роутер должен иметь метод send(message) и поддерживать message['channel'].

    Args:
        router: Объект с методом send(dict).
        routing_map: Карта (register_name, field_name) -> {channel, ...}.
        register_name: Имя регистра.
        field_name: Имя поля.
        value: Значение.
        command: Команда (write, read и т.д.).
        error_callback: При ошибке вызывается error_callback(type, context) для ErrorManager.

    Returns:
        Результат router.send(...) или None при ошибке маршрута.
    """
    key = (register_name, field_name)
    route = routing_map.get(key)
    if not route or not isinstance(route, dict):
        if error_callback:
            error_callback(ROUTING_NOT_FOUND, {
                "register": register_name,
                "field": field_name,
                "command": command,
            })
        return None
    channel = route.get("channel")
    if not channel:
        if error_callback:
            error_callback(ROUTING_NOT_FOUND, {
                "register": register_name,
                "field": field_name,
                "route": route,
            })
        return None
    message = {
        "command": command,
        "register": register_name,
        "field": field_name,
        "value": value,
        "channel": channel,
    }
    try:
        result = router.send(message)
        if result and result.get("status") == "error" and error_callback:
            error_callback(MESSAGE_LOST, {
                "register": register_name,
                "field": field_name,
                "channel": channel,
                "result": result,
            })
        return result
    except Exception as e:
        if error_callback:
            error_callback(PROCESS_UNREACHABLE, {
                "register": register_name,
                "field": field_name,
                "channel": channel,
                "exception": str(e),
            })
        return None
