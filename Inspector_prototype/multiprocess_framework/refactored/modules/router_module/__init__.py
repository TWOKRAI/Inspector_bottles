# -*- coding: utf-8 -*-
"""
router_module — менеджер маршрутизации сообщений.

Публичный API:
    RouterManager   — основной класс; создавайте один на процесс/поток
    MessageChannel  — базовый класс для всех каналов
    QueueChannel    — канал поверх multiprocessing.Queue / queue.Queue
    RouterAdapter   — интеграционный адаптер для process_module
    IRouterManager  — интерфейс RouterManager
    IMessageChannel — интерфейс канала
"""
from .core.router_manager import RouterManager
from .channels.base_channel import MessageChannel
from .channels.queue_channel import QueueChannel
from .adapters.router_adapter import RouterAdapter
from .interfaces import IRouterManager, IMessageChannel

__all__ = [
    "RouterManager",
    "MessageChannel",
    "QueueChannel",
    "RouterAdapter",
    "IRouterManager",
    "IMessageChannel",
]
