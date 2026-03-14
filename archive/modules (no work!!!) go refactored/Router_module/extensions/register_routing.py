# -*- coding: utf-8 -*-
"""
Content-Based Router для сообщений об обновлении регистров.
Регистрируется в RouterManager; один и тот же код используется в app и на бэкенде.
Часть multiprocess_framework.
"""
from typing import Dict, Any, Optional

# Регистр-провайдер: объект с методом get_field_metadata(register_name, field_name) -> dict
# В dict может быть ключ 'routing' с полями: channel (имя канала), и опционально target_process, queue_type.


def get_routing_metadata(
    registers_provider: Any,
    register_name: str,
    field_name: str,
) -> Optional[Dict[str, Any]]:
    """
    Читает метаданные маршрутизации для поля регистра.
    
    Args:
        registers_provider: объект с get_field_metadata(register_name, field_name)
        register_name: имя регистра (например 'draw', 'camera')
        field_name: имя поля (например 'dp', 'source')
    
    Returns:
        Словарь routing из метаданных поля или None.
    """
    if not hasattr(registers_provider, 'get_field_metadata'):
        return None
    metadata = registers_provider.get_field_metadata(register_name, field_name)
    return metadata.get('routing') if isinstance(metadata, dict) else None


def _register_update_channel_handler(
    message: Dict[str, Any],
    registers_provider: Any,
) -> Dict[str, Any]:
    """
    Content-Based Router: по содержимому сообщения (register, field) определяет канал.
    Возвращает результат для Dispatcher: {'status': 'success', 'channel': name}.
    """
    register_name = message.get('register')
    field_name = message.get('field')
    if not register_name or not field_name:
        return {
            'status': 'error',
            'reason': 'register_update message must have register and field',
        }
    routing = get_routing_metadata(registers_provider, register_name, field_name)
    if not routing or not isinstance(routing, dict):
        return {
            'status': 'success',
            'channel': 'default_queue',
            'handler': 'register_update',
        }
    channel = routing.get('channel')
    if not channel:
        return {
            'status': 'success',
            'channel': 'default_queue',
            'handler': 'register_update',
        }
    return {
        'status': 'success',
        'channel': channel,
        'handler': 'register_update',
    }


def register_register_routing(
    router_manager: Any,
    registers_provider: Any,
) -> bool:
    """
    Регистрирует в RouterManager Content-Based Router для типа сообщения register_update.
    Вызывается и в app, и на бэкенде с одним и тем же RouterManager и провайдером регистров.
    
    Args:
        router_manager: экземпляр RouterManager
        registers_provider: объект с get_field_metadata(register_name, field_name), например RegistersManager
    
    Returns:
        True если регистрация прошла успешно.
    """
    if not hasattr(router_manager, 'register_channel_handler'):
        return False
    handler = lambda msg: _register_update_channel_handler(msg, registers_provider)
    return router_manager.register_channel_handler(
        key='register_update',
        handler=handler,
        expects_full_message=True,
        tags=['register', 'routing'],
    )


def create_register_update_message(
    register_name: str,
    field_name: str,
    value: Any,
    sender: str = 'app',
) -> Dict[str, Any]:
    """
    Формирует словарь сообщения для обновления регистра (подходит для Message.create и router.send).
    
    Args:
        register_name: имя регистра
        field_name: имя поля
        value: новое значение
        sender: отправитель
    
    Returns:
        Словарь с полями type, register, field, value, sender для отправки через RouterManager.
    """
    return {
        'type': 'register_update',
        'register': register_name,
        'field': field_name,
        'value': value,
        'sender': sender,
    }
