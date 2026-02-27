"""
Router Module (Refactored) - Менеджер маршрутизации сообщений.

Использует BaseManager + ObservableMixin для единообразия со всеми менеджерами системы.
Интегрируется с Dispatch модулем для интеллектуальной маршрутизации сообщений.
"""

from .core.router_manager import RouterManager
from .channels.base_channel import MessageChannel
from .channels.queue_channel import QueueChannel
from .adapters.router_adapter import RouterAdapter
from .interfaces import IRouterManager, IMessageChannel

__all__ = [
    'RouterManager',
    'MessageChannel',
    'QueueChannel',
    'RouterAdapter',
    'IRouterManager',
    'IMessageChannel',
]

