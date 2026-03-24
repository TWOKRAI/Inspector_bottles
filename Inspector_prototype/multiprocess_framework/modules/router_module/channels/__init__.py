"""Каналы для маршрутизации сообщений."""

from .base_channel import MessageChannel
from .queue_channel import QueueChannel

__all__ = ['MessageChannel', 'QueueChannel']

